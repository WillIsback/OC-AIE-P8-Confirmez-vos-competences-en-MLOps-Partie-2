"""Publication et téléchargement des artefacts du modèle sur le Hub Hugging Face (ADR-002).

    uv run python scripts/model_hub.py fetch            # révision figée de model_revision.txt
    uv run python scripts/model_hub.py publish          # HF_TOKEN requis, met à jour la révision
    uv run python scripts/model_hub.py card             # publie docs/model-card.md (README)

`fetch` télécharge le dépôt modèle à la révision figée (un SHA de commit, jamais `main`),
puis vérifie les empreintes SHA-256 du manifeste en chargeant le modèle.
`publish` envoie `artifacts/` en un commit et écrit son SHA dans `model_revision.txt`,
à committer avec le code qui l'utilise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from credit_scoring.hub import REPO_ID, pinned_revision  # noqa: E402
from credit_scoring.model import load_model  # noqa: E402

REVISION_FILE = ROOT / "model_revision.txt"
DEFAULT_DIR = ROOT / "artifacts"


def fetch(dest: Path, revision: str) -> None:
    snapshot_download(REPO_ID, revision=revision, local_dir=dest, repo_type="model")
    model = load_model(dest)  # vérifie les empreintes
    print(f"✅ {model.version} @ {revision[:7]} dans {dest}")


def publish(source: Path, private: bool) -> str:
    load_model(source)  # ne publie que des artefacts cohérents
    api = HfApi()
    api.create_repo(REPO_ID, repo_type="model", private=private, exist_ok=True)
    commit = api.upload_folder(
        repo_id=REPO_ID,
        folder_path=source,
        repo_type="model",
        commit_message="Artefacts home-credit-serving v2 (export P6)",
    )
    revision = commit.oid
    REVISION_FILE.write_text(revision + "\n", encoding="utf-8")
    print(f"✅ publié : {commit.commit_url}\n   révision figée dans {REVISION_FILE.name}")
    return revision


def publish_card(card: Path) -> None:
    """Publie la model card ; n'affecte pas la révision figée des artefacts."""
    commit = HfApi().upload_file(
        path_or_fileobj=str(card),
        path_in_repo="README.md",
        repo_id=REPO_ID,
        repo_type="model",
        commit_message="Model card",
    )
    print(f"✅ model card publiée : {commit.commit_url}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--dest", type=Path, default=DEFAULT_DIR)
    p = sub.add_parser("publish")
    p.add_argument("--source", type=Path, default=DEFAULT_DIR)
    p.add_argument("--private", action="store_true")
    c = sub.add_parser("card")
    c.add_argument("--file", type=Path, default=ROOT / "docs/model-card.md")
    args = parser.parse_args()
    if args.command == "fetch":
        fetch(args.dest, pinned_revision(REVISION_FILE))
    elif args.command == "card":
        publish_card(args.file)
    else:
        publish(args.source, args.private)
    return 0


if __name__ == "__main__":
    sys.exit(main())
