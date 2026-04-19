from src.utils.peca_utils import detect_file_type, extract_rtf_text


# Minimal STF-shaped RTF: font/color tables, a paragraph with accented
# characters escaped as \'XX hex pairs (the form STF's downloadTexto.asp
# emits). This is the shape that the previous `import striprtf` + call
# to `striprtf.rtf_to_text` silently dropped via AttributeError.
_MINIMAL_STF_RTF = (
    b"{\\rtf1\\ansi\\deff0"
    b"{\\fonttbl{\\f0\\froman Times New Roman;}}"
    b"{\\colortbl;\\red0\\green0\\blue0;}"
    b"\\pard\\plain "
    b"Ementa: AGRAVO REGIMENTAL. FALSIFICA\\'c7\\'c3O DE DOCUMENTO P\\'daBLICO. "
    b"\\par "
    b"1. Inexiste teratologia na decis\\'e3o atacada."
    b"\\par }"
)


def test_extracts_plain_portuguese_with_accents():
    out = extract_rtf_text(_MINIMAL_STF_RTF)
    assert out is not None
    assert "Ementa: AGRAVO REGIMENTAL" in out
    assert "FALSIFICAÇÃO DE DOCUMENTO PÚBLICO" in out
    assert "Inexiste teratologia na decisão atacada" in out


def test_detect_file_type_recognizes_rtf_magic():
    # The detector branches on magic bytes before extract_rtf_text runs;
    # guard that RTFs starting with the canonical {\rtf prefix are routed
    # to the RTF path even when Content-Type is missing.
    class _FakeResp:
        headers = {}
        content = _MINIMAL_STF_RTF

    assert detect_file_type(_FakeResp()) == "rtf"
