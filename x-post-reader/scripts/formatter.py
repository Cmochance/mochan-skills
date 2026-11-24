"""Thread reconstruction and Markdown + YAML rendering for x-post-reader."""

from __future__ import annotations

from dataclasses import asdict
import json
import re
from typing import Callable, List, Optional, Set, Tuple

from tiers import PostItem


_LEADING_MENTION_RE = re.compile(r"^\s*@([A-Za-z0-9_]{1,15})\b")


def _same_author(a: PostItem, b: PostItem) -> bool:
    if a.author_id and b.author_id:
        return a.author_id == b.author_id
    return a.author_handle.lower() == b.author_handle.lower()


def _snowflake_sort_key(post: PostItem) -> Tuple[int, str]:
    try:
        return (int(post.id), post.created_at)
    except (TypeError, ValueError):
        return (0, post.created_at)


def _is_leading_mention_to_other(post: PostItem, author_handle: str) -> bool:
    m = _LEADING_MENTION_RE.match(post.text or "")
    if not m:
        return False
    return m.group(1).lower() != author_handle.lower()


def find_same_author_subroot(focal: PostItem, upstream: List[PostItem]) -> Tuple[List[PostItem], List[PostItem]]:
    """Split upstream into (cross_author_context_prefix, same_author_segment_ending_at_focal)."""
    if not upstream:
        return [], [focal]

    split_idx = len(upstream) - 1
    while split_idx > 0 and _same_author(upstream[split_idx - 1], focal):
        split_idx -= 1

    # Ensure focal is anchored inside same_author_segment
    prefix = [p for p in upstream[:split_idx] if p.id != focal.id]
    segment = [p for p in upstream[split_idx:] if _same_author(p, focal)]
    if not any(p.id == focal.id for p in segment):
        segment.append(focal)
    return prefix, segment


def reconstruct_self_thread(
    focal: PostItem,
    upstream: List[PostItem],
    tier3_posts: List[PostItem],
    include_replies: int = 0,
    verify_parent_fn: Optional[Callable[[PostItem], Optional[PostItem]]] = None,
    walk_ancestors_fn: Optional[Callable[[PostItem], Tuple[List[PostItem], bool]]] = None,
) -> Tuple[List[PostItem], List[PostItem], bool]:
    """Reconstruct cross-author context + focal-anchored self-thread + optional replies.

    Returns (ordered_posts, extra_replies, verification_incomplete).
    """
    context_prefix, same_author_segment = find_same_author_subroot(focal, upstream)
    sub_root = same_author_segment[0] if same_author_segment else focal
    sub_root_sort = _snowflake_sort_key(sub_root)

    prefix_ids: Set[str] = {p.id for p in context_prefix if p.id}
    author_posts_by_id: dict[str, PostItem] = {}
    for item in same_author_segment:
        if item.id and not item.is_retweet:
            author_posts_by_id[item.id] = item
    if focal.id and not focal.is_retweet:
        author_posts_by_id.setdefault(focal.id, focal)

    seen_tier3_ids: Set[str] = set()
    other_replies: List[PostItem] = []
    downstream_candidates: List[PostItem] = []

    for item in tier3_posts:
        if not item.id or item.id in seen_tier3_ids:
            continue
        seen_tier3_ids.add(item.id)
        if item.is_retweet:
            continue

        if _same_author(item, focal):
            if item.id in author_posts_by_id or item.id in prefix_ids:
                continue
            if _snowflake_sort_key(item) < sub_root_sort:
                continue
            if verify_parent_fn is None and _is_leading_mention_to_other(item, focal.author_handle):
                continue
            downstream_candidates.append(item)
        elif item.id not in prefix_ids:
            other_replies.append(item)

    downstream_candidates.sort(key=_snowflake_sort_key)
    verification_incomplete = False

    for item in downstream_candidates:
        if item.id in author_posts_by_id:
            continue

        if item.replying_to_status:
            if item.replying_to_status in author_posts_by_id:
                author_posts_by_id[item.id] = item
            continue

        if verify_parent_fn is None:
            author_posts_by_id[item.id] = item
            continue

        verified = verify_parent_fn(item)
        if verified is None:
            verification_incomplete = True
            continue

        parent_id = verified.replying_to_status
        if parent_id and parent_id in author_posts_by_id:
            author_posts_by_id[item.id] = verified
            continue

        # Recover intermediate folded same-author floors if parent was still by focal author
        if (
            parent_id
            and verified.replying_to
            and verified.replying_to.lower() == focal.author_handle.lower()
            and walk_ancestors_fn is not None
        ):
            chain, walk_truncated = walk_ancestors_fn(verified)
            if any(p.replying_to_status in author_posts_by_id or p.id in author_posts_by_id for p in chain):
                for node in chain:
                    if node.id and _same_author(node, focal) and _snowflake_sort_key(node) >= sub_root_sort:
                        author_posts_by_id.setdefault(node.id, node)
                if walk_truncated:
                    verification_incomplete = True

    same_author_sorted = sorted(author_posts_by_id.values(), key=_snowflake_sort_key)
    combined: List[PostItem] = []
    emitted_ids: Set[str] = set()
    for p in [*context_prefix, *same_author_sorted]:
        if p.id and p.id not in emitted_ids:
            emitted_ids.add(p.id)
            combined.append(p)
        elif not p.id:
            combined.append(p)

    if not combined:
        combined = [focal]

    extra_replies = other_replies[: max(include_replies, 0)] if include_replies > 0 else []
    return combined, extra_replies, verification_incomplete


def _yaml_escape(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("\t", " ")
    )
    return f'"{escaped}"'


def _sanitize_single_line(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _sanitize_alt_text(value: str) -> str:
    return _sanitize_single_line(value).replace("[", "\\[").replace("]", "\\]")


def _format_post_block(post: PostItem) -> List[str]:
    lines: List[str] = []
    if post.text:
        lines.append(post.text.strip())
    if post.media:
        lines.append("")
        for idx, m in enumerate(post.media, start=1):
            label = _sanitize_alt_text(m.alt_text) or f"{m.type}_{idx}"
            lines.append(f"![{label}]({m.url})" if m.type == "photo" else f"- [{label}]({m.url})")
    if post.poll and post.poll.get("choices"):
        lines.append("")
        lines.append("**Poll:**")
        for choice in post.poll["choices"]:
            label = _sanitize_single_line(str(choice.get("label", "")))
            lines.append(f"- {label}: {choice.get('count', 0)} ({choice.get('percentage', 0)}%)")
    if post.quote:
        q = post.quote
        lines.append("")
        lines.append(f"> **Quoted @{q.author_handle} ({_sanitize_single_line(q.author_name)})** — [link]({q.url})")
        for qline in (q.text or "").strip().splitlines():
            lines.append(f"> {qline}")
    return lines


def render_markdown(
    *,
    focal: PostItem,
    posts: List[PostItem],
    post_type: str,
    tier_used: str,
    completeness: str,
    completeness_note: str = "",
    article_markdown: str = "",
    article_title: str = "",
    extra_replies: Optional[List[PostItem]] = None,
) -> str:
    """Render normalized post/article/thread result into YAML-fronted Markdown."""
    total_media = sum(len(p.media) for p in posts)
    has_replies = int(focal.stats.get("replies") or 0) > 0
    author_display = f"@{focal.author_handle} ({focal.author_name})"

    lines: List[str] = [
        "---",
        f"tweet_id: {_yaml_escape(focal.id)}",
        f"url: {_yaml_escape(focal.url)}",
        f"author: {_yaml_escape(author_display)}",
        f"created_at: {_yaml_escape(focal.created_at)}",
        f"post_type: {_yaml_escape(post_type)}",
        f"thread_count: {len(posts)}",
        f"tier_used: {_yaml_escape(tier_used)}",
        f"completeness: {_yaml_escape(completeness)}",
        f"has_replies: {'true' if has_replies else 'false'}",
        f"media_count: {total_media}",
        "---",
        "",
    ]

    if completeness != "full":
        note_lines = (completeness_note or "Content may be incomplete.").strip().splitlines()
        lines.append(f"> [!WARNING] Partial Fetch (`{completeness}`): {note_lines[0]}")
        for cont in note_lines[1:]:
            lines.append(f"> {cont}")
        lines.append("")

    if post_type == "article":
        raw_title = article_title or (focal.article.title if focal.article else "") or "X Article"
        title = _sanitize_single_line(raw_title) or "X Article"
        lines.append(f"# {title}")
        lines.append("")
        if focal.article and focal.article.cover_url:
            lines.append(f"![cover]({focal.article.cover_url})")
            lines.append("")
        body = article_markdown.strip() or (focal.article.blocks_markdown if focal.article else "") or focal.text
        lines.append(body.strip())
    else:
        show_headers = (
            len(posts) > 1
            or (len(posts) == 1 and (posts[0].id != focal.id or not _same_author(posts[0], focal)))
        )
        if show_headers:
            total = len(posts)
            for idx, item in enumerate(posts, start=1):
                lines.append(f"## [{idx}/{total}] @{item.author_handle} · [source]({item.url})")
                lines.append("")
                lines.extend(_format_post_block(item))
                if idx < total:
                    lines.extend(["", "---", ""])
        else:
            lines.extend(_format_post_block(posts[0] if posts else focal))

    if extra_replies:
        lines.extend(["", "---", "", "## Top Replies", ""])
        for reply in extra_replies:
            reply_lines = (reply.text or "").strip().splitlines() or [""]
            lines.append(f"- **@{reply.author_handle}**: {reply_lines[0]} ([link]({reply.url}))")
            for cont in reply_lines[1:]:
                lines.append(f"  {cont}")

    return "\n".join(lines).rstrip() + "\n"


def render_json_payload(
    *,
    focal: PostItem,
    posts: List[PostItem],
    post_type: str,
    tier_used: str,
    completeness: str,
    completeness_note: str = "",
    article_markdown: str = "",
    article_title: str = "",
    extra_replies: Optional[List[PostItem]] = None,
) -> str:
    """Render structured JSON payload for programmatic consumers."""
    payload = {
        "tweet_id": focal.id,
        "url": focal.url,
        "author": {
            "id": focal.author_id,
            "handle": focal.author_handle,
            "name": focal.author_name,
        },
        "created_at": focal.created_at,
        "post_type": post_type,
        "tier_used": tier_used,
        "completeness": completeness,
        "completeness_note": completeness_note,
        "article_title": article_title or (focal.article.title if focal.article else None),
        "article_markdown": article_markdown or (focal.article.blocks_markdown if focal.article else None),
        "posts": [asdict(p) for p in posts],
        "extra_replies": [asdict(r) for r in (extra_replies or [])],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
