from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BAT_FILES = sorted(ROOT.glob("*.bat"))
PS1_FILES = sorted(ROOT.glob("*.ps1"))


def test_batch_wrappers_hold_no_text_cmd_could_mis_parse():
    """cmd mis-parsed the Korean lines and ran their fragments as commands (reported 2026-09-17)."""
    assert BAT_FILES
    for path in BAT_FILES:
        data = path.read_bytes()
        data.decode("ascii")  # Korean belongs in the .ps1 file, not here
        assert data.count(b"\r\n") == data.count(b"\n"), f"{path.name}: needs CRLF line endings"
        assert b"chcp" not in data, f"{path.name}: a code page change is what broke the parsing"
        script = path.with_suffix(".ps1")
        assert script.is_file() and script.name.encode() in data, f"{path.name}: must start {script.name}"


def test_powershell_scripts_start_with_a_bom_so_windows_powershell_reads_korean():
    assert PS1_FILES
    for path in PS1_FILES:
        data = path.read_bytes()
        assert data.startswith(b"\xef\xbb\xbf"), f"{path.name}: Windows PowerShell reads a BOM-less file as cp949"
        data.decode("utf-8")
