#!/usr/bin/env python3
"""Package vscode/ as a .vsix (R159 step 7), with nothing installed.

A .vsix is a zip: the extension's files under extension/, a manifest VS
Code's installer reads, and the content types. vsce makes the same thing
from npm; this makes it from python's own zipfile, so the extension stays
the plain JavaScript with no build step and no dependencies it is.

    tools/vscode-vsix.py --version X.Y.Z --out dist/NAME.vsix

The version is BuilderBot's own (bb version --semver), written into the
package.json inside the archive, so an install says which BuilderBot it came
from; the Files API version it speaks is package.json's builderbotApi.
"""
import argparse
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape  # nosemgrep: python.lang.security.use-defused-xml.use-defused-xml (escaping the manifest it writes; nothing is parsed)

HERE = Path(__file__).resolve().parent.parent / "vscode"
FILES = ("package.json", "extension.js", "README.md", "lib/client.js", "lib/ws.js", "lib/term.js")

TYPES = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension=".json" ContentType="application/json"/>
<Default Extension=".js" ContentType="application/javascript"/>
<Default Extension=".md" ContentType="text/markdown"/>
<Default Extension=".vsixmanifest" ContentType="text/xml"/>
</Types>
"""


def manifest(pkg):
    e = lambda k: escape(str(pkg.get(k, "")))  # noqa: E731
    return f"""<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="{e('name')}" Version="{e('version')}" Publisher="{e('publisher')}"/>
    <DisplayName>{e('displayName')}</DisplayName>
    <Description xml:space="preserve">{e('description')}</Description>
    <Categories>{escape(','.join(pkg.get('categories', [])))}</Categories>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{escape(pkg['engines']['vscode'])}"/>
    </Properties>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code"/>
  </Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/>
    <Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/README.md" Addressable="true"/>
  </Assets>
</PackageManifest>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    pkg = json.loads((HERE / "package.json").read_text())
    pkg["version"] = a.version
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", TYPES)
        z.writestr("extension.vsixmanifest", manifest(pkg))
        for f in FILES:
            body = json.dumps(pkg, indent=2) + "\n" if f == "package.json" else (HERE / f).read_text()
            z.writestr(f"extension/{f}", body)
    print(f"{out} ({out.stat().st_size} bytes): BuilderBot for VS Code {a.version}")


if __name__ == "__main__":
    main()
