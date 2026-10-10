import pytest

from speakhired.engines.vocab import context_terms, correct_transcript, prepare_speech, whisper_prompt


@pytest.mark.parametrize("text, expected", [
    ("When would you prefer Claude Anthropic models over ChatGPT models?", "When would you prefer Clawd Anthropic models over Chat G P T models?"),
    ("Compare GPT-4 with Claude.", "Compare G P T four with Clawd."),
    ("We deploy with kubectl on EKS and use CI/CD.", "We deploy with cube control on E K S and use C I C D."),
    ("Put nginx in front of a REST API using OAuth and JWT.", "Put engine X in front of a rest A P I using Oh Auth and J W T."),
    ("PostgreSQL, MySQL and NoSQL; query with SQL or GraphQL.", "Postgres Q L, My S Q L and No S Q L; query with S Q L or Graph Q L."),
    ("Reduced latency by 40% for the client/server link.", "Reduced latency by 40 percent for the client server link."),
    ("It is open‑source — and “fast”.", "It is open-source , and \"fast\"."),
    ("Is the UK team OK with it", "Is the U K team okay with it."),
    ("Write idempotent YAML and JSON for the SRE team.", "Write eye-dem-poh-tent yam-ull and Jay-son for the S R E team."),
    ("Node.js and Next.js with C++ and C#.", "Node J S and Next J S with C plus plus and C sharp."),
])
def test_questions_are_prepared_the_way_an_engineer_says_them(text, expected):
    assert prepare_speech(text) == expected


def test_words_that_are_not_terms_are_left_alone():
    assert prepare_speech("Please express yourself, then spark a discussion about flask design.") == "Please express yourself, then spark a discussion about flask design."
    assert prepare_speech("") == ""


@pytest.mark.parametrize("heard, fixed", [
    ("I would pick chat gpt for open ended chats", "I would pick ChatGPT for open ended chats"),
    ("we compared chat g p t and claude", "we compared ChatGPT and Claude"),
    ("I deployed on cooper netties with cube control", "I deployed on Kubernetes with kubectl"),
    ("we used post gress and my sequel with node js", "we used PostgreSQL and MySQL with Node.js"),
    ("the g p t four model", "the GPT-4 model"),
    ("I used an a p i and a w s", "I used an API and AWS"),
    ("it is oh auth with j w t tokens", "it is OAuth with JWT tokens"),
])
def test_misheard_terms_are_fixed(heard, fixed):
    assert correct_transcript(heard)[0] == fixed


def test_risky_fixes_need_interview_context():
    # "pseudo code" and "jason" are ordinary language unless the interview is about the term
    assert correct_transcript("I wrote pseudo code and spoke to Jason")[0] == "I wrote pseudo code and spoke to Jason"
    assert correct_transcript("then we parse jason from the response", ["JSON"])[0] == "then we parse JSON from the response"
    assert correct_transcript("I like Express and Spark", [])[0] == "I like Express and Spark"          # untouched
    assert correct_transcript("I know node js", [])[0] == "I know Node.js"


def test_sounds_like_a_context_term_in_two_words():
    fixed, changes = correct_transcript("we used lang chain with olama", ["LangChain", "Ollama"])
    assert fixed == "we used LangChain with Ollama" and {c[1] for c in changes} == {"LangChain", "Ollama"}


def test_normal_sentences_do_not_change():
    s = "I led a team of four engineers and we shipped the payments service in two months, which reduced errors by forty percent."
    assert correct_transcript(s, ["Kafka", "Kubernetes", "ChatGPT"]) == (s, [])


def test_interview_context_terms_come_from_the_question_and_the_stack():
    terms = context_terms("When would you prefer Claude Anthropic models over ChatGPT models?", extra=["Spring Boot", "Kafka"])
    assert {"Claude", "Anthropic", "ChatGPT", "Spring Boot", "Kafka"} <= set(terms)
    prompt, hot = whisper_prompt(terms)
    assert "ChatGPT" in prompt and "ChatGPT" in hot and prompt.startswith("Um,") and len(prompt) < 900
