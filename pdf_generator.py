"""
PDF Generator Module

Regenerates PDF documents from markdown using docforge's export engine.
Supports both resume and cover letter document types.

Run standalone test:
    python pdf_generator.py --index 41 --type resume
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

# Add agents_sdk to path for imports
AGENTS_SDK_ROOT = Path(__file__).parent.parent / "agents_sdk"
if str(AGENTS_SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENTS_SDK_ROOT))

from agents_sdk.docforge.core.export import export_pdf_structured
from agents_sdk.docforge.core.models import DocumentProfile, ExportConfig, PdfStyle
from agents_sdk.docforge.export_engine import (
    MermaidRenderer,
    VisualRendererRouter,
    _resolve_binary,
    detect_pdf_engine,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Style presets for different document types
RESUME_STYLE = PdfStyle(
    pdf_engine="xelatex",
    margin="0.75in",
    margin_top="0.7in",
    margin_bottom="0.7in",
    fontsize="10pt",
    documentclass="article",
    toc=False,
    colorlinks=True,
    linkcolor="blue",
    urlcolor="blue",
    header_right=r"\thepage",
    rich_preamble=True,
    first_page_mode="resume_compact",
    suppress_title_block=True,
    show_header_on_first_page=False,
    show_footer_on_first_page=False,
)

COVER_LETTER_STYLE = PdfStyle(
    pdf_engine="xelatex",
    margin="1in",
    margin_top="1in",
    margin_bottom="1in",
    fontsize="11pt",
    documentclass="letter",
    toc=False,
    colorlinks=True,
    linkcolor="blue",
    urlcolor="blue",
    header_right=r"\thepage",
    rich_preamble=True,
    first_page_mode="cover_letter_business",
    suppress_title_block=False,
    show_header_on_first_page=True,
    show_footer_on_first_page=False,
)


def check_dependencies() -> bool:
    """Check that required dependencies are available."""
    if not _resolve_binary("pandoc"):
        logger.error("pandoc not found - required for PDF generation")
        return False
    if not detect_pdf_engine():
        logger.error("No LaTeX engine found (xelatex/pdflatex required)")
        return False
    return True


def get_document_style(doc_type: str) -> PdfStyle:
    """Get the appropriate PDF style for a document type."""
    if doc_type == "resume":
        return RESUME_STYLE
    elif doc_type == "cover_letter":
        return COVER_LETTER_STYLE
    else:
        # Default style
        return RESUME_STYLE


def generate_pdf(
    input_path: Path,
    output_path: Path,
    doc_type: str = "resume",
    timeout: int = 180,
) -> tuple[bool, str]:
    """
    Generate a PDF from a markdown file.

    Args:
        input_path: Path to the input markdown file
        output_path: Path where the PDF should be written
        doc_type: Document type ('resume' or 'cover_letter')
        timeout: Maximum time in seconds for PDF generation

    Returns:
        Tuple of (success: bool, error_message: str)
    """
    if not input_path.exists():
        return False, f"Input file not found: {input_path}"

    if not output_path.parent.exists():
        output_path.parent.mkdir(parents=True, exist_ok=True)

    # Read and analyze markdown for document profile
    content = input_path.read_text(encoding="utf-8")
    profile = DocumentProfile.from_markdown(content)

    # Get appropriate style for document type
    style = get_document_style(doc_type)

    # Set up export config
    config = ExportConfig(
        input_path=input_path,
        output_dir=output_path.parent,
        output_name=output_path.stem,
        dpi=150,
        run_timeout=timeout,
        generate_pdf=True,
        generate_epub=False,
    )

    # Initialize renderer (MermaidRenderer handles diagrams)
    renderer = VisualRendererRouter()

    logger.info(f"Generating PDF for {input_path.name} (type: {doc_type})")
    logger.info(f"  Output: {output_path}")
    logger.info(f"  Style: {style.first_page_mode}")

    # Run export
    result = export_pdf_structured(config, profile, style, renderer)

    if result.success:
        logger.info(f"  PDF generated successfully ({result.size_kb}KB, {result.duration_ms}ms)")
        return True, ""
    else:
        error_msg = f"PDF generation failed: {result.error_code} - {result.error_message}"
        logger.error(f"  {error_msg}")
        return False, error_msg


def regenerate_job_pdf(
    bundle_dir: Path,
    doc_type: str = "resume",
    timeout: int = 180,
) -> tuple[bool, str, Optional[Path]]:
    """
    Regenerate PDF for a job bundle.

    Args:
        bundle_dir: Path to the job bundle directory (e.g., applications/all_jobs/41_signant_...)
        doc_type: Document type ('resume' or 'cover_letter')
        timeout: Maximum time in seconds for PDF generation

    Returns:
        Tuple of (success: bool, error_message: str, output_path: Optional[Path])
    """
    # Determine input/output filenames
    if doc_type == "resume":
        input_file = bundle_dir / "resume.md"
        output_file = bundle_dir / "resume.pdf"
    elif doc_type == "cover_letter":
        input_file = bundle_dir / "cover_letter.md"
        output_file = bundle_dir / "cover_letter.pdf"
    else:
        return False, f"Unknown document type: {doc_type}", None

    if not input_file.exists():
        return False, f"Input file not found: {input_file}", None

    success, error = generate_pdf(input_file, output_file, doc_type, timeout)
    return success, error, output_file if success else None


def main():
    """CLI for standalone PDF generation."""
    parser = argparse.ArgumentParser(description="Generate PDF from markdown")
    parser.add_argument("--index", type=int, required=True, help="Job index")
    parser.add_argument(
        "--type",
        choices=["resume", "cover_letter"],
        default="resume",
        help="Document type",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Timeout in seconds (default: 180)",
    )
    parser.add_argument(
        "--check-deps",
        action="store_true",
        help="Check dependencies and exit",
    )
    args = parser.parse_args()

    if args.check_deps:
        ok = check_dependencies()
        sys.exit(0 if ok else 1)

    # Check dependencies first
    if not check_dependencies():
        logger.error("Dependencies check failed")
        sys.exit(1)

    # Find job bundle directory
    project_root = Path(__file__).parent.resolve()
    applications_dir = project_root / "applications" / "all_jobs"
    prefix = f"{args.index:02d}_"

    bundle_dir = None
    for entry in applications_dir.iterdir():
        if entry.is_dir() and entry.name.startswith(prefix):
            bundle_dir = entry
            break

    if not bundle_dir:
        logger.error(f"Job #{args.index} not found in {applications_dir}")
        sys.exit(1)

    logger.info(f"Processing job #{args.index}: {bundle_dir.name}")
    logger.info(f"Document type: {args.type}")

    success, error, output_path = regenerate_job_pdf(bundle_dir, args.type, args.timeout)

    if success:
        print(f"\nPDF generated: {output_path}")
        sys.exit(0)
    else:
        print(f"\nFailed: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
