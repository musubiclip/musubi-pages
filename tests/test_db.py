from helpers import add_clip

from pages import db


def test_queue_size_counts_unpublished_clips(d):
    for s in ["planned", "draft", "approved", "scheduled", "published", "failed"]:
        add_clip(d, "billikalesh", s)
    add_clip(d, "podcastbawaal", "draft")
    assert db.queue_size(d, "billikalesh") == 4 and db.QUEUE_LOW == 7


def test_event_is_recorded(d):
    db.event(d, "billikalesh", "paused", "2207050")
    row = d.execute("select page, kind, detail, at from events").fetchone()
    assert tuple(row)[:3] == ("billikalesh", "paused", "2207050") and row["at"]
