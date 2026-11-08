import math

import pytest

from owlet.check import Result, Status


def test_status_given_as_text_becomes_a_status():
    assert Result("PASS", "Fine.").status is Status.PASS


def test_unknown_status_is_rejected_and_lists_the_valid_ones():
    with pytest.raises(ValueError, match="PASS, WARN, FAIL, SKIP, ERROR"):
        Result("OK", "Fine.")


@pytest.mark.parametrize("summary", ["", "   ", "\n", None, 5])
def test_summary_must_be_non_empty_text(summary):
    with pytest.raises(TypeError, match="non-empty string"):
        Result(Status.PASS, summary)


@pytest.mark.parametrize("summary", ["a\nb", "a\n", "a\r\nb", "a\rb", "a\x0bb", "a\x0cb", "a\u2028b"])
def test_summary_must_be_one_line(summary):
    with pytest.raises(ValueError, match="one line"):
        Result(Status.PASS, summary)


@pytest.mark.parametrize("details", ["a string", ["fine", 5], [None]])
def test_details_must_be_a_list_of_strings(details):
    with pytest.raises(TypeError, match="details"):
        Result(Status.PASS, "Fine.", details=details)


def test_details_are_stored_as_a_tuple():
    assert Result(Status.PASS, "Fine.", details=["a", "b"]).details == ("a", "b")


@pytest.mark.xfail(reason="validating details consumes a generator, so they silently end up empty")
def test_details_from_a_generator_are_kept_or_rejected_but_not_lost():
    try:
        result = Result(Status.PASS, "Fine.", details=(line for line in ["a", "b"]))
    except TypeError:
        return
    assert result.details == ("a", "b")


@pytest.mark.parametrize("value", [object(), {1, 2}, math.nan, math.inf, -math.inf])
def test_data_must_be_strict_json(value):
    with pytest.raises(TypeError, match="JSON-serializable"):
        Result(Status.PASS, "Fine.", data={"value": value})


def test_data_is_copied_so_later_changes_do_not_reach_the_result():
    data = {"days_left": 69}
    result = Result(Status.PASS, "Fine.", data=data)
    data["days_left"] = 0
    assert result.data == {"days_left": 69}


@pytest.mark.parametrize(("name", "label"), [(None, "tls"), ("HSTS", "tls - HSTS")])
def test_label_includes_the_result_name_if_any(name, label):
    assert Result(Status.PASS, "Fine.", name=name, check_name="tls").label == label
