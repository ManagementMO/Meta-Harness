export const MOCK_TEST_OUTPUT: Record<string, string> = {
  "retry-on-schema-drift": `============================= test session starts ==============================
platform linux -- Python 3.11.8, pytest-8.1.1
collected 5 items

eval/tests/test_median.py::test_median_basic PASSED                    [ 20%]
eval/tests/test_median.py::test_median_even PASSED                     [ 40%]
eval/tests/test_median.py::test_median_single PASSED                   [ 60%]
eval/tests/test_median.py::test_median_negative PASSED                 [ 80%]
eval/tests/test_median.py::test_median_empty PASSED                    [100%]

============================== 5 passed in 2.1s ===============================`,
  "stricter-tool-hashing": `============================= test session starts ==============================
platform linux -- Python 3.11.8, pytest-8.1.1
collected 5 items

eval/tests/test_median.py::test_median_basic PASSED                    [ 20%]
eval/tests/test_median.py::test_median_even FAILED                     [ 40%]
eval/tests/test_median.py::test_median_single PASSED                   [ 60%]
eval/tests/test_median.py::test_median_negative PASSED                 [ 80%]
eval/tests/test_median.py::test_median_empty FAILED                    [100%]

=================================== FAILURES ===================================
_____________________________ test_median_even _____________________________

    def test_median_even():
>       assert median([1, 2, 3, 4]) == 2.5
E       AssertionError: assert 2 == 2.5

eval/tests/test_median.py:15: AssertionError
_____________________________ test_median_empty ____________________________

    def test_median_empty():
>       assert median([]) is None
E       TypeError: cannot unpack empty sequence

eval/tests/test_median.py:24: TypeError
=========================== 2 failed, 3 passed in 1.8s ========================`,
  "early-exit-on-auth": `============================= test session starts ==============================
platform linux -- Python 3.11.8, pytest-8.1.1
collected 5 items

eval/tests/test_median.py .....                                        [100%]

============================== 5 passed in 1.9s ===============================`,
  "more-specific-descriptions": `============================= test session starts ==============================
platform linux -- Python 3.11.8, pytest-8.1.1
collected 5 items

eval/tests/test_median.py .....                                        [100%]

============================== 5 passed in 2.3s ===============================`,
  "rewrite-tool-descriptions": `============================= test session starts ==============================
platform linux -- Python 3.11.8, pytest-8.1.1
collected 5 items

eval/tests/test_median.py .....                                        [100%]

============================== 5 passed in 2.0s ===============================`,
  "few-shot-demos": `============================= test session starts ==============================
platform linux -- Python 3.11.8, pytest-8.1.1
collected 5 items

eval/tests/test_median.py .....                                        [100%]

============================== 5 passed in 2.1s ===============================`,
};
