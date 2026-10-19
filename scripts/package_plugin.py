import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "astrbot_plugin_gatebridge"


def main() -> None:
    json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    files = [
        ROOT / "main.py",
        ROOT / "metadata.yaml",
        ROOT / "_conf_schema.json",
        ROOT / "requirements.txt",
        ROOT / "README.md",
        ROOT / "docs" / "commands.md",
        ROOT / "docs" / "publishing.md",
        *sorted((ROOT / "gatebridge").glob("*.py")),
    ]
    output = ROOT / "dist" / f"{PLUGIN_NAME}.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, f"{PLUGIN_NAME}/{path.relative_to(ROOT).as_posix()}")
    print(output)


if __name__ == "__main__":
    main()
