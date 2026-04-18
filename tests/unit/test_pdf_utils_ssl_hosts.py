from src.utils.pdf_utils import _is_stf_host


def test_matches_known_stf_subdomains():
    assert _is_stf_host("https://portal.stf.jus.br/processos/detalhe.asp?incidente=1")
    assert _is_stf_host("https://sistemas.stf.jus.br/repgeral/votacao")
    assert _is_stf_host("https://digital.stf.jus.br/decisoes-monocraticas/api/public/votos/1/conteudo.pdf")


def test_matches_apex():
    assert _is_stf_host("https://stf.jus.br/foo")


def test_rejects_non_stf():
    assert not _is_stf_host("https://example.com/x")
    assert not _is_stf_host("https://stf.jus.br.evil.com/x")
    assert not _is_stf_host("https://notstf.jus.br/x")


def test_rejects_unparseable():
    assert not _is_stf_host("")
    assert not _is_stf_host("not-a-url")
