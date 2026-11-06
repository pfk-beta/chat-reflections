import json
import zipfile
from pathlib import Path

from chat_reflections.importers import chatgpt, claude, claude_code, gemini, openwebui, perplexity

FIX = Path(__file__).parent / "fixtures"
CC = FIX / "claude_code/host/-home-x-proj"


def test_claude_code_session() -> None:
    [c] = claude_code.parse(CC / "s1.jsonl")
    assert (c.id, c.title, c.project) == ("claude_code:s1", "Naprawa testów", "/home/x/proj")
    assert [(m.role, m.content) for m in c.messages] == [
        ("user", "Napraw testy"),
        ("assistant", "Naprawione."),
        ("user", "Teraz ruff"),  # rewound "Teraz lint" and isMeta prompt dropped
        ("assistant", "OK"),
        ("user", ""),  # compact summary, only as collapsed part
        ("user", "dalej"),
        ("assistant", "Gotowe"),
    ]
    turn = c.messages[1]
    assert [p["type"] for p in turn.parts] == ["thinking", "tool", "tool", "text"]
    bash, read = turn.parts[1], turn.parts[2]
    assert (bash["name"], bash["output"], bash["is_error"]) == ("Bash", "1 failed", True)
    assert read["output"] == "print(1)"
    assert c.messages[4].parts[0]["type"] == "summary"


def test_claude_code_commands_collapsed_with_output() -> None:
    [c] = claude_code.parse(CC / "s2.jsonl")
    assert [m.content for m in c.messages] == ["/login", "! pwd", "/model opus", "Hello", "Hi!"]
    login, pwd, model = (m.parts[0] for m in c.messages[:3])
    assert login == {"type": "command", "name": "/login", "args": "", "output": "Login successful"}
    assert (pwd["name"], pwd["args"], pwd["output"]) == ("!", "pwd", "/home/x/proj")
    assert "output" not in model


def test_claude_code_subagent() -> None:
    [c] = claude_code.parse(CC / "s1/subagents/agent-a1.jsonl")
    assert c.id == "claude_code:s1-agent-a1"
    assert c.title.startswith("[subagent] Znajdź")
    assert [m.role for m in c.messages] == ["user", "assistant"]


def test_claude() -> None:
    [c] = claude.parse(FIX / "claude/conversations.json")
    assert c.id == "claude:c1"
    assert [(m.role, m.external_id) for m in c.messages] == [("user", "m1"), ("assistant", "m2")]


def test_claude_from_zip(tmp_path: Path) -> None:
    zpath = tmp_path / "claude_conversations-000.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(FIX / "claude/conversations.json", "conversations.json")
    assert len(list(claude.parse(zpath))) == 1


def test_perplexity_skips_empty_answer() -> None:
    [c] = perplexity.parse(FIX / "perplexity/conversations-20261105.json")
    assert [m.role for m in c.messages] == ["user", "assistant", "user"]
    assert c.messages[1].model == "pro"


def test_openwebui_follows_current_branch() -> None:
    [c] = openwebui.parse(FIX / "openwebui/chat-export-1.json")
    assert [m.content for m in c.messages] == [
        "Co zrobić z rysunkami dzieci?",
        "Zrób z nich album.",
    ]
    assert c.messages[1].model == "qwen"


def test_raw_kept_without_nested_messages() -> None:
    [c] = claude.parse(FIX / "claude/conversations.json")
    assert c.raw["uuid"] == "c1" and "chat_messages" not in c.raw
    assert c.messages[0].raw["uuid"] == "m1"
    [o] = openwebui.parse(FIX / "openwebui/chat-export-1.json")
    assert "history" not in o.raw["chat"]


def test_chatgpt_current_branch_thinking_and_markers() -> None:
    c, _ = chatgpt.parse(FIX / "chatgpt/conversations-000.json")
    assert c.id == "chatgpt:g1"
    user, answer = c.messages
    assert user.content == "Jak zrobić pierogi z kapustą?"
    assert answer.content == "Ugotuj kapustę kiszoną i podsmaż z cebulą."
    assert answer.model == "gpt-5"
    assert [p["type"] for p in answer.parts] == ["thinking", "text"]
    assert c.raw["id"] == "g1" and "mapping" not in c.raw


def test_chatgpt_images_empty_answers_untitled() -> None:
    _, c = chatgpt.parse(FIX / "chatgpt/conversations-000.json")
    assert c.title == "(untitled)" and c.updated_at == c.created_at
    assert [m.content for m in c.messages] == ["[image]\n\nCo jest na zdjęciu?", "Halo?"]


def test_chatgpt_sharded_zip(tmp_path: Path) -> None:
    zpath = tmp_path / "chatgpt_export.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(FIX / "chatgpt/conversations-000.json", "conversations-000.json")
        zf.write(FIX / "chatgpt/conversations-000.json", "conversations-001.json")
        zf.writestr("shared_conversations.json", "[]")
    assert len(list(chatgpt.parse(zpath))) == 4


def test_gemini_groups_by_app_link() -> None:
    c, single = gemini.parse(FIX / "gemini/MyActivity.json")
    assert c.id == "gemini:abc123"
    assert c.title == "Jak wypisać hello world w Pythonie?"
    assert [m.role for m in c.messages] == ["user", "assistant", "user", "assistant"]
    assert c.messages[2].content == "and now in Rust?"
    assert [m.content for m in single.messages] == ["draw a cat"]


def test_gemini_html_to_markdown() -> None:
    [c, _] = gemini.parse(FIX / "gemini/MyActivity.json")
    assert c.messages[1].content == (
        "### Odpowiedź\n\nUżyj `print` & **gotowe**:\n\n"
        "- krok *pierwszy*\n- krok drugi, [docs](https://python.org)\n\n---\n\n1. a"
    )
    assert '```\nfn main() {\n    println!("hi");\n}\n```' in c.messages[3].content


def test_gemini_from_takeout_zip(tmp_path: Path) -> None:
    zpath = tmp_path / "takeout-1.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(FIX / "gemini/MyActivity.json", "Takeout/My Activity/Gemini Apps/MyActivity.json")
        zf.writestr("Takeout/Access Log Activity/devices.json", "{}")
    assert len(list(gemini.parse(zpath))) == 2


def test_chatgpt_uploaded_and_generated_images(tmp_path: Path) -> None:
    zpath = tmp_path / "chatgpt_export.zip"
    lib = [
        {
            "file_id": "file_gen1",
            "file_name": "Sketch of a cat.png",
            "origination_thread_id": "g2",
            "created_at": "2026-01-02T00:00:05+00:00",
        }
    ]
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(FIX / "chatgpt/conversations-000.json", "conversations-000.json")
        zf.writestr("file-x.dat", b"\x89PNG")
        zf.writestr("file_gen1.dat", b"\x89PNG")
        zf.writestr("conversation_asset_file_names.json", '{"file-x.dat": "photo.jpg"}')
        zf.writestr("library_files.json", json.dumps(lib))
    _, c = chatgpt.parse(zpath)
    upload, _, generated = c.messages  # no timestamps in g2 -> image goes last
    assert upload.content == "Co jest na zdjęciu?"
    assert [p["type"] for p in upload.parts] == ["image", "text"]
    assert upload.parts[0]["member"] == "file-x.dat" and upload.parts[0]["name"] == "photo.jpg"
    assert generated.role == "assistant" and generated.content == "Sketch of a cat"
    assert generated.parts[0]["member"] == "file_gen1.dat"


def test_gemini_images_from_takeout(tmp_path: Path) -> None:
    zpath = tmp_path / "takeout-1.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(FIX / "gemini/MyActivity.json", "Takeout/My Activity/Gemini Apps/MyActivity.json")
        zf.writestr("Takeout/My Activity/Gemini Apps/my-cat.jpg", b"\xff\xd8\xff")
        zf.writestr("Takeout/My Activity/Gemini Apps/generated-cat.png", b"\x89PNG")
    _, c = gemini.parse(zpath)
    prompt, answer = c.messages
    assert [p.get("member", "").rsplit("/")[-1] for p in prompt.parts] == ["", "my-cat.jpg"]
    assert answer.content == "" and answer.parts[0]["name"] == "generated-cat.png"
