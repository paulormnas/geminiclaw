import pytest
from src.skills.document_processor.extractors.base import ExtractedDocument
from src.skills.document_processor.extractors.registry import ExtractorRegistry
from src.skills.document_processor.chunker import DocumentChunker

@pytest.fixture
def mock_text_file(tmp_path):
    file_path = tmp_path / "test.txt"
    file_path.write_text("Hello World\n\nThis is a test document.\n\nAnother paragraph.")
    return str(file_path)

@pytest.fixture
def mock_csv_file(tmp_path):
    file_path = tmp_path / "data.csv"
    file_path.write_text("id,name\n1,Alice\n2,Bob")
    return str(file_path)

def test_text_extractor_via_registry(mock_text_file):
    registry = ExtractorRegistry()
    doc = registry.extract(mock_text_file)
    
    assert doc.format == "txt"
    assert "Hello World" in doc.text_content
    assert doc.title == "test.txt"
    assert not doc.extraction_errors

def test_csv_extractor_via_registry(mock_csv_file):
    registry = ExtractorRegistry()
    doc = registry.extract(mock_csv_file)
    
    assert doc.format == "csv"
    assert "id,name" in doc.text_content
    assert "1,Alice" in doc.text_content
    assert doc.title == "data.csv"
    assert len(doc.tables) == 1
    assert doc.tables[0]["header"] == ["id", "name"]
    assert not doc.extraction_errors

def test_chunker_fixed_size():
    doc = ExtractedDocument(
        source_path="/fake/test.txt",
        format="txt",
        title="test.txt",
        text_content="A" * 2000
    )
    chunker = DocumentChunker(max_chunk_size=1000, overlap=100, strategy="fixed", prepend_context=False)
    chunks = chunker.chunk(doc, "doc_123")
    
    assert len(chunks) == 3
    # 1st chunk: 0 to 1000
    # 2nd chunk: 900 to 1900
    # 3rd chunk: 1800 to 2000
    assert chunks[0].document_id == "doc_123"

def test_chunker_paragraphs():
    doc = ExtractedDocument(
        source_path="/fake/test.txt",
        format="txt",
        title="test.txt",
        text_content="P1\n\nP2\n\nP3"
    )
    chunker = DocumentChunker(max_chunk_size=2, overlap=0, strategy="paragraph", prepend_context=False)
    chunks = chunker.chunk(doc, "doc_123")
    
    # Each chunk should contain roughly one paragraph if max size is small
    assert len(chunks) == 3
    assert chunks[0].content == "P1"
    assert chunks[1].content == "P2"
    assert chunks[2].content == "P3"

def test_chunker_context_prefix():
    doc = ExtractedDocument(
        source_path="/fake/test.txt",
        format="txt",
        title="test.txt",
        text_content="Content"
    )
    chunker = DocumentChunker(max_chunk_size=1000, overlap=100, strategy="fixed", prepend_context=True)
    chunks = chunker.chunk(doc, "doc_123")
    
    assert len(chunks) == 1
    assert chunks[0].context_prefix == "Documento: test.txt (TXT)"
    assert chunks[0].content.startswith("Documento: test.txt (TXT)\n\nContent")
