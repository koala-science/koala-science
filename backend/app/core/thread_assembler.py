"""
Assemble a comment thread into a single text block for embedding.

Structure: paper title + abstract as context, then the full reply chain
in depth-first order with indentation to preserve conversational structure.
"""
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import Comment, Paper


async def assemble_thread_text(root_comment_id: str, db: AsyncSession) -> tuple[str, str] | None:
    """
    Build the embeddable text for a thread rooted at root_comment_id.
    Returns (root_comment_id, text) or None if the comment doesn't exist.

    The root_comment_id returned may differ from input if the input is a reply
    (we walk up to the root).
    """
    import uuid

    comment_id = uuid.UUID(root_comment_id)

    # Load the comment to find its root and paper
    result = await db.execute(
        select(Comment).where(Comment.id == comment_id)
    )
    comment = result.scalar_one_or_none()
    if not comment:
        return None

    # Walk up to root comment
    root = comment
    while root.parent_id is not None:
        parent_result = await db.execute(
            select(Comment).where(Comment.id == root.parent_id)
        )
        root = parent_result.scalar_one_or_none()
        if not root:
            break

    # Load paper for context
    paper_result = await db.execute(select(Paper).where(Paper.id == root.paper_id))
    paper = paper_result.scalar_one_or_none()
    if not paper:
        return None

    # Load all comments for this paper (cheaper than recursive queries)
    all_comments_result = await db.execute(
        select(Comment)
        .options(joinedload(Comment.author))
        .where(Comment.paper_id == root.paper_id)
        .order_by(Comment.created_at.asc())
    )
    all_comments = all_comments_result.scalars().all()

    # Build child lookup
    children: dict[str, list] = {}
    comment_map: dict[str, Comment] = {}
    for c in all_comments:
        comment_map[str(c.id)] = c
        parent_key = str(c.parent_id) if c.parent_id else None
        if parent_key:
            children.setdefault(parent_key, []).append(c)

    # Build thread text depth-first from root
    lines = [
        f"Paper: {paper.title}",
        f"Abstract: {paper.abstract}",
        "",
        "Discussion thread:",
    ]

    def walk(comment: Comment, depth: int = 0):
        indent = "  " * depth
        author_name = comment.author.name if comment.author else "Unknown"
        lines.append(f"{indent}[{author_name}]: {comment.content_markdown}")
        for child in children.get(str(comment.id), []):
            walk(child, depth + 1)

    walk(comment_map[str(root.id)])

    return str(root.id), "\n".join(lines)
