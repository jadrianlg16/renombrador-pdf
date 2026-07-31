from pathlib import Path

import pytest

from app.naming import (
    safe_upload_relative_path,
    sanitize_folder_name,
    sanitize_pdf_name,
    unique_directory,
    unique_target,
)


def test_sanitize_preserves_accents_and_removes_invalid_characters():
    assert sanitize_pdf_name('  MARÍA: GARCÍA / LÓPEZ  ') == 'MARÍA GARCÍA LÓPEZ.pdf'


def test_sanitize_removes_duplicate_pdf_extension():
    assert sanitize_pdf_name('JUAN PÉREZ.pdf') == 'JUAN PÉREZ.pdf'


def test_reserved_windows_name_is_safe():
    assert sanitize_pdf_name('CON') == 'CON_.pdf'


def test_unique_target_adds_suffix(tmp_path: Path):
    (tmp_path / 'ANA.pdf').write_bytes(b'x')
    assert unique_target(tmp_path, 'ANA.pdf').name == 'ANA (2).pdf'


@pytest.mark.parametrize(
    'raw, expected',
    [
        ('Escrituras Junio/S-0001.pdf', 'Escrituras Junio/S-0001.pdf'),
        ('sub\\carpeta\\acta.pdf', 'sub/carpeta/acta.pdf'),
        ('../../../etc/salida.pdf', 'etc/salida.pdf'),
        ('C:/Users/Jesus/Escritorio/acta.pdf', 'Users/Jesus/Escritorio/acta.pdf'),
        ('  ACTA FINAL .PDF ', 'ACTA FINAL .PDF'),
    ],
)
def test_safe_upload_relative_path_accepts_only_contained_pdfs(raw: str, expected: str):
    assert safe_upload_relative_path(raw) == expected


@pytest.mark.parametrize('raw', ['notas.txt', '', '.pdf', '../..', 'carpeta/'])
def test_safe_upload_relative_path_rejects_everything_else(raw: str):
    assert safe_upload_relative_path(raw) is None


def test_safe_upload_relative_path_keeps_the_extension_on_very_long_names():
    result = safe_upload_relative_path(f"{'A' * 400}.pdf")
    assert result is not None and result.endswith('.pdf') and len(result) <= 120


def test_sanitize_folder_name_collapses_paths_to_a_single_level():
    assert sanitize_folder_name('C:/Users/Jesus/Escrituras: Junio') == 'Escrituras Junio'
    assert sanitize_folder_name('../..') == ''


def test_unique_directory_does_not_reuse_an_existing_batch(tmp_path: Path):
    (tmp_path / 'Lote').mkdir()
    assert unique_directory(tmp_path, 'Lote').name == 'Lote (2)'
