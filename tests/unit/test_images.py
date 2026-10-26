from rag_pre_ingest.models.document import Block, Page
from rag_pre_ingest.pipeline.images import mark_decorative


def test_only_small_repeated_images_are_decorative() -> None:
    pages = [
        Page(
            page_number=n,
            width=100,
            height=100,
            blocks=[
                Block(id=f"img{n}", type="image", bbox=(0, 0, 10, 10)),
                Block(
                    id=f"ocr{n}",
                    type="paragraph",
                    text="LOGO",
                    markdown="LOGO",
                    source="ocr",
                    bbox=(1, 1, 9, 9),
                ),
            ],
        )
        for n in (1, 2)
    ]
    marked = mark_decorative(pages, {"img1": "same", "img2": "same"})
    assert all(page.blocks[0].is_decorative for page in marked)
    assert all(len(page.blocks) == 1 for page in marked)
    assert not pages[0].blocks[0].is_decorative
    unique = mark_decorative(pages, {"img1": "one", "img2": "two"})
    assert not any(page.blocks[0].is_decorative for page in unique)
