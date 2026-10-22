import json

import pytest

from engine import clipper
from engine.clipper import caption_chunks, crop_expression, crop_x, main_face, tidy_clips


def word(text, start, end):
    return {"word": text, "start": start, "end": end}


def test_crop_expression_slides_within_a_shot():
    assert crop_expression([(0, 10)]) == "10"
    assert crop_expression([(0, 10), (2.5, 40)]) == "if(lt(t,2.500),10+(40-10)*(t-0.000)/2.500,40)"


def test_crop_expression_cuts_hard_between_shots():
    # equal timestamps mark a shot boundary: jump straight from 10 to 40, no slide
    assert crop_expression([(0, 10), (2.5, 10), (2.5, 40), (5, 40)]) == "if(lt(t,2.500),10,if(lt(t,5.000),40,40))"


def test_crop_x_clamps_to_frame():
    assert crop_x(None, 1920, 608) == 656
    assert crop_x(0, 1920, 608) == 0
    assert crop_x(1900, 1920, 608) == 1312


def test_captions_break_on_size_gap_and_punctuation():
    words = [word("a", 0, 0.2), word("b,", 0.2, 0.4), word("c.", 0.4, 0.6), word("d", 0.6, 0.8),
             *[word(str(i), 2.0 + i * 0.2, 2.2 + i * 0.2) for i in range(7)]]
    assert [[w["word"] for w in c] for c in caption_chunks(words)] == [["a", "b,", "c."], ["d"], ["0", "1", "2", "3", "4", "5"], ["6"]]


def test_tidy_snaps_drops_overlaps_and_ranks():
    words = [word(str(i), i, i + 0.9) for i in range(200)]
    scores = {"hook": 3, "standalone": 3, "payoff": 3, "emotion": 3}
    raw = [
        {**scores, "start": 10.2, "end": 40.3, "title": "a", "cold_open_start": 30.1, "cold_open_end": 33.4},
        {**scores, "start": 20, "end": 50, "title": "overlaps a"},
        {**scores, "start": 100, "end": 105, "title": "too short"},
        {**scores, "hook": 5, "start": 60, "end": 90, "title": "best", "cold_open_start": 60, "cold_open_end": 63},
    ]
    clips = tidy_clips(raw, words, 5)
    assert [c["title"] for c in clips] == ["best", "a"]
    assert (clips[1]["start"], clips[1]["end"], clips[1]["cold_open"]) == (9.75, 39.94, [29.9, 32.94])
    assert clips[0]["cold_open"] is None


def test_captions_never_overlap():
    from engine.clipper import build_ass
    words = [word("one", 0, 0.3), word("two", 0.3, 0.6), word("three.", 0.6, 1.0), word("four", 1.05, 1.4), word("five", 3.0, 3.3)]
    clip = {"start": 0, "end": 4, "cold_open": None, "hook_text": "hi"}
    lines = [l.split(",") for l in build_ass(clip, words).splitlines() if l.startswith("Dialogue: 0")]
    spans = [(l[1], l[2]) for l in lines]
    assert spans == [("0:00:00.00", "0:00:00.30"), ("0:00:00.30", "0:00:00.60"), ("0:00:00.60", "0:00:01.05"),
                     ("0:00:01.05", "0:00:01.55"), ("0:00:03.00", "0:00:03.30")]


def test_split_words_rejoin():
    from engine.clipper import build_ass
    words = [word("all", 0, 0.3), word("-nighters", 0.3, 0.6)]
    ass = build_ass({"start": 0, "end": 1, "cold_open": None, "hook_text": "hi"}, words)
    assert "all{\\c&H0000E5FF&}-nighters" in ass


def test_youtube_words_and_segments(tmp_path):
    import json
    from engine.clipper import group_segments, youtube_words
    caption = tmp_path / "c.json3"
    caption.write_text(json.dumps({"events": [
        {"tStartMs": 1000, "segs": [{"utf8": ">> so"}, {"utf8": " [music]", "tOffsetMs": 100}, {"utf8": " [sound", "tOffsetMs": 120}, {"utf8": " of", "tOffsetMs": 140}, {"utf8": " throat]", "tOffsetMs": 160}, {"utf8": " in", "tOffsetMs": 200}]},
        {"tStartMs": 1500, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 4000, "segs": [{"utf8": "college"}, {"utf8": ".", "tOffsetMs": 300}]},
    ]}))
    words = youtube_words(caption)
    assert words == [{"word": "so", "start": 1.0, "end": 1.2}, {"word": "in", "start": 1.2, "end": 2.0},
                     {"word": "college.", "start": 4.0, "end": 4.5}]
    assert [s["text"] for s in group_segments(words)] == ["so in", "college."]


def test_moment_problems_names_each_bad_field():
    from engine.clipper import moment_problems
    good = {"start": 1, "end": 30, "title": "t", "hook_text": "h", "reason": "r", "hook": 3, "standalone": 3, "payoff": 3, "emotion": 3}
    assert moment_problems([good]) == []
    bad = {**good, "end": "30", "hook": 7, "title": ""}
    assert moment_problems([good, bad]) == ["moment 2: end must be a number of seconds", "moment 2: title is missing",
                                            "moment 2: hook must be a whole number from 1 to 5"]


def test_shifted_moves_clip_words_and_pieces_together():
    from engine.clipper import clip_timeline, shifted
    words = [word("a", 100.0, 100.5), word("b", 101.0, 101.4)]
    clip = {"start": 100.0, "end": 102.0, "cold_open": [101.0, 101.4]}
    moved, moved_words = shifted(clip, words, 99.0)
    assert (moved["start"], moved["end"], [round(t, 6) for t in moved["cold_open"]]) == (1.0, 3.0, [2.0, 2.4])

    def rounded(timeline):
        return [(w["word"], round(w["start"], 6), round(w["end"], 6)) for w in timeline]

    assert rounded(clip_timeline(moved, moved_words)) == rounded(clip_timeline(clip, words))


def test_cards_move_with_the_clip_and_land_in_clip_time():
    from engine.clipper import card, shifted
    clip = {"start": 100.0, "end": 130.0, "cold_open": [120.0, 124.0],
            "stat": {"at": 105.0, "value": "90%", "sub_at": 106.0}, "deal": {"at": 140.0, "value": "₹5 Cr"}}
    moved, _ = shifted(clip, [], 99.0)
    assert (moved["stat"]["at"], moved["stat"]["sub_at"]) == (6.0, 7.0)
    assert card(moved, "stat")["at"] == 9.0
    assert card(moved, "deal") is None


def test_moment_problems_checks_cards():
    from engine.clipper import moment_problems
    good = {"start": 1, "end": 30, "title": "t", "hook_text": "h", "reason": "r", "hook": 3, "standalone": 3, "payoff": 3, "emotion": 3}
    assert moment_problems([{**good, "stat": {"at": 5, "value": "90%"}, "hook_parts": {"big": "90%"}}]) == []
    assert moment_problems([{**good, "deal": {"at": 50, "value": "₹5 Cr"}}]) == ["moment 1: deal at must fall between start and end"]


def test_breathe_pads_but_never_reaches_the_next_word():
    from engine.clipper import breathe
    words = [word("a", 0.0, 0.5), word("b", 2.0, 2.4), word("c", 2.5, 3.0), word("d", 5.0, 5.4)]
    assert breathe(2.0, 3.0, words, 0.25, 0.7) == (1.75, 3.7)
    assert breathe(2.5, 3.0, words, 0.25, 0.7) == (2.4, 3.7)
    assert breathe(2.0, 2.4, words, 0.25, 0.7) == (1.75, 2.44)


def test_snap_prefers_whole_sentences_nearby():
    from engine.clipper import snap
    words = [word("so", 0.0, 0.3), word("we", 0.3, 0.6), word("built", 0.6, 1.0), word("it.", 1.0, 1.4),
             word("then", 1.5, 1.8), word("they", 1.8, 2.1), word("asked", 2.1, 2.5), word("why?", 2.5, 3.0), word("next", 6.0, 6.3)]
    assert snap(1.9, words, "end") == 1.4
    assert snap(0.4, words, "start") == 0.0
    assert snap(1.9, words, "start") == 1.5
    assert snap(6.2, words, "end") == 6.3


def test_skip_drops_a_span_and_keeps_cards_in_clip_time():
    from engine.clipper import card, clip_timeline, pieces_for, shifted
    words = [word("a", 10.0, 10.5), word("b", 12.0, 12.4), word("c", 20.0, 20.5)]
    clip = {"start": 10.0, "end": 21.0, "cold_open": None, "skip": [[13.0, 19.0]], "stat": {"at": 20.0, "value": "9"}}
    assert pieces_for(clip) == [(10.0, 13.0), (19.0, 21.0)]
    assert [(w["word"], w["start"]) for w in clip_timeline(clip, words)] == [("a", 0.0), ("b", 2.0), ("c", 4.0)]
    assert card(clip, "stat")["at"] == 4.0
    moved, _ = shifted(clip, words, 5.0)
    assert moved["skip"] == [[8.0, 14.0]]


def test_main_face_ignores_a_hand_low_in_the_frame():
    speaker, hand = (200, 80, 120, 150), (40, 400, 60, 60)
    assert main_face([hand, speaker]) == speaker
    assert main_face([]) is None


def test_a_section_is_reused_when_it_covers_the_clip(tmp_path):
    import os
    from engine.clipper import covering_section
    (tmp_path / "100.00-160.00.mp4").touch()
    (tmp_path / "100.00-160.00.video.mp4").touch()
    stale = tmp_path / "300.00-360.00.part.mp4"
    stale.touch()
    os.utime(stale, (0, 0))
    assert covering_section(tmp_path, 102, 158).name == "100.00-160.00.mp4"
    assert covering_section(tmp_path, 98, 158) is None
    assert covering_section(tmp_path, 302, 358) is None


def test_end_screen_takes_a_logo_file_and_needs_a_video_for_the_channel(tmp_path):
    import pytest
    from engine.clipper import END, end_screen

    logo = tmp_path / "brand.png"
    logo.write_bytes(b"png")
    END.update(choice=str(logo), name=" Cleevo ", line="cleevo.in")
    screen = end_screen(tmp_path)
    assert screen == {"logo": tmp_path / "end-logo.png", "kind": "logo", "name": "Cleevo", "line": "cleevo.in"}
    END.update(choice="channel")
    with pytest.raises(SystemExit):
        end_screen(tmp_path)
    END.update(choice=None)

MOMENT_30S = {"start": 10.0, "end": 40.0, "title": "Fixture", "hook_text": "Ninety percent is just water",
              "hook_parts": {"kicker": "Your cleaner is", "big": "90%", "punch": "Just water"}, "reason": "r",
              "hook": 3, "standalone": 3, "payoff": 3, "emotion": 3}
THEME = {"hot": "#7c5cff", "sun": "#ffd23f", "font": "Poppins"}


def test_offline_never_calls_youtube(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSUBI_CLIPS_OFFLINE", "1")
    monkeypatch.setattr(clipper, "run", lambda *a, **k: pytest.fail("called " + a[0][0]))
    assert clipper.find_stream(tmp_path, {"url": "https://youtu.be/x"}) is None
    with pytest.raises(RuntimeError, match="no section covers"):
        clipper.video_section(tmp_path, {"url": "https://youtu.be/x"}, {"start": 10, "end": 40, "cold_open": None}, None)


def test_faceless_wide_shots_are_cropped_not_letterboxed():
    f = clipper.frame_filter(1920, 1080, 608, 1080, [(0, 656)], [False, False, False])
    assert f.startswith("crop=608:1080") and "boxblur" not in f


def test_theme_sets_colours_and_font():
    html = clipper.reel_page({"duration": 30}, "v2", 30, 30, "", {"hot": "#7c5cff", "sun": "#ffd23f", "font": "Poppins"})
    assert "--hot: #7c5cff" in html and "--display: \"Poppins\"" in html and "Poppins-ExtraBold.ttf" in html


def test_theme_font_without_a_file_keeps_the_template_face():
    html = clipper.reel_page({"duration": 30}, "v2", 30, 30, "", {"hot": "#7c5cff", "sun": "#ffd23f",
                                                                 "font": "Bricolage Grotesque"})
    assert "Bricolage Grotesque-ExtraBold.ttf" not in html and '--display: "Bricolage Grotesque"' in html


def test_render_one_turns_an_engine_exit_into_an_error(tmp_path, monkeypatch):
    words = [word(f"w{i}." if i % 10 == 9 else f"w{i}", i * 0.5, i * 0.5 + 0.4) for i in range(120)]
    (tmp_path / "transcript.json").write_text(json.dumps({"language": "en", "source": "youtube",
                                                          "segments": clipper.group_segments(words)}))
    (tmp_path / "meta.json").write_text(json.dumps({"title": "f", "url": "", "language": "en"}))
    monkeypatch.setattr(clipper, "find_stream", lambda w, m: None)
    monkeypatch.setattr(clipper, "video_section", lambda w, m, c, s: ("v.mp4", 0.0))
    monkeypatch.setattr(clipper, "face_detector", lambda: None)

    def render_styled(*a, **k):
        raise SystemExit("hyperframes render failed")
    monkeypatch.setattr(clipper, "render_styled", render_styled)
    with pytest.raises(RuntimeError, match="hyperframes render failed"):
        clipper.render_one(tmp_path, MOMENT_30S, tmp_path / "r.mp4", theme=THEME)


@pytest.mark.slow
def test_render_one_makes_a_vertical_reel(fixture_workdir, tmp_path, monkeypatch):
    monkeypatch.setenv("MUSUBI_CLIPS_OFFLINE", "1")
    out = clipper.render_one(fixture_workdir, MOMENT_30S, tmp_path / "r.mp4", theme=THEME)
    assert clipper.probe_size(out) == (1080, 1920) and 29 < clipper.duration_of(out) < 32


WORDS_95_TO_141 = [word(f"w{i}", 95.0 + i * 0.5, 95.4 + i * 0.5) for i in range(92)]
CARDS = [{"at": 15.0, "title": "Who", "body": "Ex ISRO engineer", "hold": 4}, {"at": 28.0, "title": "Why", "body": "Built it in a garage", "hold": 4}]


def tidied(start, end):
    return {"start": start, "end": end, "cold_open": None, "skip": [], "hook_text": "h", "title": "t"}


def test_intro_moves_captions_after_the_voiceover():
    clip = {**tidied(100.0, 140.0), "intro": 4.0}
    assert clipper.pieces_for(clip)[0] == (clip["start"] - 4.0, clip["start"])
    data = clipper.reel_data(clip, WORDS_95_TO_141, duration=44.0)
    assert data["intro"] == {"seconds": 4.0} and min(w["s"] for w in data["words"]) >= 4.0


def test_cards_land_in_reel_time_after_the_intro():
    clip = {**tidied(100.0, 140.0), "intro": 4.0, "cards": [{"at": 110.0, "title": "Who", "body": "Ex ISRO", "hold": 4}]}
    card = clipper.reel_data(clip, WORDS_95_TO_141, duration=44.0)["cards"][0]
    assert card["at"] == round(4.0 + 110.0 - clip["start"], 3) and card["title"] == "Who"


def test_outro_starts_when_the_moment_ends():
    clip = {**tidied(100.0, 140.0), "intro": 4.0, "outro": {"seconds": 3.0, "text": "Save this"}}
    out = clipper.reel_data(clip, WORDS_95_TO_141, duration=47.0)["outro"]
    assert out == {"at": round(4.0 + clip["end"] - clip["start"], 3), "seconds": 3.0, "text": "Save this"}


def test_cards_move_with_the_section():
    moved, _ = clipper.shifted({**tidied(100.0, 140.0), "cards": [{"at": 110.0, "title": "Who"}]}, [], 90.0)
    assert moved["cards"][0]["at"] == 20.0


@pytest.mark.slow
def test_render_one_with_the_layer_is_intro_plus_clip_plus_outro(fixture_workdir, tmp_path, vo_4s, vo_3s, monkeypatch):
    monkeypatch.setenv("MUSUBI_CLIPS_OFFLINE", "1")
    out = clipper.render_one(fixture_workdir, {**MOMENT_30S, "cards": CARDS}, tmp_path / "r.mp4", theme=THEME,
                             intro={"audio": vo_4s, "seconds": 4.0}, outro={"audio": vo_3s, "seconds": 3.0, "text": "Save this"})
    assert 36.5 < clipper.duration_of(out) < 38.5


def test_a_section_must_reach_back_over_the_pre_roll(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSUBI_CLIPS_OFFLINE", "1")
    monkeypatch.setattr(clipper, "run", lambda *a, **k: pytest.fail("called " + a[0][0]))
    (tmp_path / "sections").mkdir()
    (tmp_path / "sections" / "20.00-60.00.mp4").touch()
    words = [word(f"w{i}.", i * 0.5, i * 0.5 + 0.4) for i in range(120)]
    (tmp_path / "transcript.json").write_text(json.dumps({"language": "en", "segments": [{"words": words}]}))
    (tmp_path / "meta.json").write_text(json.dumps({"url": "https://youtu.be/x", "language": "en"}))
    with pytest.raises(RuntimeError, match="no section covers"):
        clipper.render_one(tmp_path, {**MOMENT_30S, "start": 22.0, "end": 50.0}, tmp_path / "r.mp4",
                           intro={"audio": tmp_path / "vo.mp3", "seconds": 4.0})
    with pytest.raises(ValueError, match="too early for a 4.0s intro"):
        clipper.render_one(tmp_path, {**MOMENT_30S, "start": 3.0, "end": 30.0}, tmp_path / "r.mp4",
                           intro={"audio": tmp_path / "vo.mp3", "seconds": 4.0})


def test_no_words_keeps_the_moment_as_given_and_has_no_captions():
    clip = tidy_clips([{**MOMENT_30S, "start": 2.0, "end": 19.5}], [], 1)[0]
    assert (clip["start"], clip["end"]) == (2.0, 19.5)
    data = clipper.reel_data(clip, [], duration=17.5)
    assert data["words"] == [] and data["groups"] == []


@pytest.mark.slow
def test_render_one_without_words_renders_the_whole_moment(tmp_path, monkeypatch):
    import subprocess
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=20",
                    "-f", "lavfi", "-i", "sine=frequency=220:duration=20", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(tmp_path / "source.mp4")], check=True)
    (tmp_path / "transcript.json").write_text(json.dumps({"language": "en", "source": "none", "segments": []}))
    (tmp_path / "meta.json").write_text(json.dumps({"title": "cat", "url": "", "path": str(tmp_path / "source.mp4"),
                                                    "language": "en"}))
    monkeypatch.setenv("MUSUBI_CLIPS_OFFLINE", "1")
    moment = {**MOMENT_30S, "start": 2.0, "end": 18.0, "cards": [{"at": 6.0, "title": "Why", "body": "Cats knead", "hold": 4}]}
    out = clipper.render_one(tmp_path, moment, tmp_path / "out" / "r.mp4", theme=THEME)
    assert clipper.probe_size(out) == (1080, 1920) and 15 < clipper.duration_of(out) < 17
