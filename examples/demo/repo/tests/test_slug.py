from slugkit.slug import slugify, truncate


def test_truncate_keeps_whole_words():
    assert truncate("hello brave new world", 12) == "hello brave"


def test_truncate_short_text_unchanged():
    assert truncate("hi", 10) == "hi"


def test_slugify_lowercases_and_hyphenates():
    assert slugify("Hello Brave World") == "hello-brave-world"


def test_slugify_drops_punctuation():
    assert slugify("Hello, World!") == "hello-world"
