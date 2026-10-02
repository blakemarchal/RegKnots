"""2026-10-02 — NMC sample exams parsed into structured questions."""
from ingest import exam_questions as e

BASE = e.Question(source_file="q101_deck_general-part_a.pdf", number=0, pool="Q101",
                  part="Deck General – Part I", exam="Master/Chief Mate of Unlimited Tonnage",
                  topic_key="deck_general", topic_label="Deck General Knowledge")


def test_inline_and_split_choices_multiline_stems_and_answers():
    lines = [
        "1.", "You are in charge of a towing vessel that operates exclusively on inland waters.",
        "What will be accepted as proper credentials?",
        "A.", "Social Security card", "B.", "No credentials are required", "C.", "Merchant Mariner",
        "Credential", "D.", "State driver's license", "Correct answer: C",
        "2. In writing up the logbook you make an error. How is it corrected?",
        "A. Erase it", "B. Cross out the error with a single line and initial it", "C. Blot it out",
        "D. Remove the page", "Correct answer: B",
    ]
    [one, two] = e.parse_lines(lines, BASE)
    assert one.number == 1 and one.answer == "C" and not one.needs_figure
    assert one.stem.startswith("You are in charge") and one.stem.endswith("proper credentials?")
    assert one.choices == {"A": "Social Security card", "B": "No credentials are required",
                           "C": "Merchant Mariner Credential", "D": "State driver's license"}
    assert two.choices["B"].startswith("Cross out") and two.answer == "B"
    assert (two.pool, two.exam, two.topic_key) == ("Q101", "Master/Chief Mate of Unlimited Tonnage", "deck_general")


def test_figures_and_reference_books_are_flagged():
    lines = [
        "1. Vessel \"A\" is overtaking vessel \"B\" as shown in illustration D017RR below. Who stands on?",
        "A. A", "B. B", "Correct answer: B",
        "2. Use the white pages of The Stability Data Reference Book to find the free surface correction.",
        "A. 0.12 ft", "B. 0.21 ft", "C. 0.33 ft", "D. 0.41 ft", "Correct answer: C",
        "3. What does a flashing blue light indicate on inland waters?",
        "A. A law enforcement vessel", "B. A work boat", "Correct answer: A",
    ]
    assert [q.needs_figure for q in e.parse_lines(lines, BASE)] == [True, True, False]


def test_a_question_without_a_listed_answer_is_skipped_and_numbering_resyncs():
    lines = [
        "1. First?", "A. x", "B. y", "Correct answer: E",          # answer not among the choices
        "2. Second?", "A. x", "B. y", "Correct answer: A",
        "4. A stray numbered line inside text is not a question start",
        "3. Third?", "A. x", "B. y", "Correct answer: B",
    ]
    assert [q.number for q in e.parse_lines(lines, BASE)] == [2, 3]
