import pytest

from speakhired.privacy import Redactor, contains_pii, describe, has_phone, redact

RESUME = """Priya Sharma
priya.sharma@example.com | +91 98765 43210 | linkedin.com/in/priya-sharma | github.com/priya
Address: Flat 402, Sai Residency, Madhapur, Hyderabad - 500081
DOB: 14/03/1998
Marital Status: Single
Aadhaar: 1234 5678 9012   PAN: ABCDE1234F   Passport: K1234567
Account No: 123456789012  Card 4111 1111 1111 1111

Summary
Backend engineer. Priya Sharma built Kafka consumers with Spring Boot and Jenkins at Acme Pay, Hyderabad.
Worked with Sai Teja and Anita Rao. Reference: Mr Ravi Kumar, Infosys. Reduced latency by 40% for 2 million events (2017 - 2021)."""

SECRETS = ["Priya", "priya", "98765", "linkedin", "github.com", "Madhapur", "500081", "14/03/1998", "Single", "1234 5678", "ABCDE1234F",
           "K1234567", "123456789012", "4111", "Sai Teja", "Anita Rao", "Ravi Kumar", "example.com"]
KEEP = ["Kafka", "Spring Boot", "Jenkins", "Acme Pay", "Infosys", "Hyderabad", "2017 - 2021", "40%", "2 million events", "Backend engineer"]


def test_every_kind_of_personal_detail_is_removed_and_the_useful_content_is_kept():
    r = Redactor()
    out = r.clean(RESUME)
    for secret in SECRETS:
        assert secret not in out, f"leaked: {secret}"
    for keep in KEEP:
        assert keep in out, f"over-redacted: {keep}"
    assert set(r.summary()) >= {"name", "email", "phone number", "link", "address", "birth date", "bank or card number", "personal detail"}


def test_restore_puts_the_original_text_back_exactly():
    r = Redactor()
    assert r.restore(r.clean(RESUME)) == RESUME
    assert r.restore_json({"a": ["[NAME_1] built it"], "n": 3}) == {"a": ["Priya Sharma built it"], "n": 3}
    assert r.restore("[NAME_99] stays") == "[NAME_99] stays"  # unknown tokens are left alone


def test_same_value_gets_same_token_and_summary_never_contains_values():
    r = Redactor()
    out = r.clean("Mail a@b.com or a@b.com again, or c@d.org")
    assert out.count("[EMAIL_1]") == 2 and "[EMAIL_2]" in out and r.summary() == {"email": 2}
    assert "a@b.com" not in str(r.summary()) and describe(r.summary()) == "2 emails"


@pytest.mark.parametrize("sentence", [
    "I built Kafka consumers in Python and deployed them with Docker Compose and Kubernetes on AWS.",
    "We moved from Jenkins to GitHub Actions and cut the build time by 40% across 12 services.",
    "Experience with Spring Boot, Hibernate, PostgreSQL, Redis and REST APIs; strong grasp of CI/CD.",
    "Led a team of 4 engineers between Jan 2021 and Mar 2023, shipping the Orders Service and Payments Platform.",
    "Reduced p99 latency from 900 ms to 220 ms for 2,000,000 requests per day (2019 - 2023).",
    "I am comfortable with Apache Spark, Apache Airflow, Terraform, Grafana and Prometheus.",
    "Tell me about yourself, why this role, and what do you know about the company?",
])
def test_technical_text_is_never_changed(sentence):
    r = Redactor()
    assert r.clean(sentence) == sentence and r.summary() == {}


def test_phone_year_range_and_card_rules():
    assert not has_phone("JNTU Hyderabad, 2017 - 2021 and Jan 2021 - Present") and has_phone("+91 98765 43210")
    for number in ("4111 1111 1111 1111", "4111-1111-1111-1112", "1234567890123456"):  # any 13 to 19 digit run is treated as a card or account
        assert "[ACCOUNT_1]" in Redactor().clean(f"card {number}") and "4111" not in Redactor().clean(f"card {number}")
    out = Redactor().clean("Aadhaar 1234 5678 9012, PAN ABCDE1234F, passport K1234567, IFSC HDFC0001234")
    assert out.count("[ID_") == 4 and "ABCDE" not in out and "HDFC0001234" not in out


def test_names_from_labels_honorifics_and_known_terms():
    out = Redactor(extra_terms=["Lakshmi"]).clean("Name: Ananya Rao\nFather's name: Venkat Rao\nThanks to Lakshmi and Dr. Meera Iyer for the review.")
    for gone in ("Ananya", "Venkat", "Lakshmi", "Meera"):
        assert gone not in out
    assert contains_pii("write to me at a@b.com") and not contains_pii("I use Kafka") and "[EMAIL_1]" in redact("a@b.com")


def test_employers_colleges_and_cities_are_kept_but_people_are_removed():
    doc = "Priya Sharma\nExperience\nAcme Pay, Software Engineer, Hyderabad\nJNTU Hyderabad, B.Tech\nTata Consultancy Services, Chennai\nWorked with Ravi Kumar on the Orders Service."
    r = Redactor()
    out = r.clean(doc)
    for kept in ("Acme Pay", "JNTU Hyderabad", "Tata Consultancy Services", "Chennai", "Orders Service"):
        assert kept in out
    assert "Priya" not in out and "Ravi Kumar" not in out and r.summary() == {"name": 2}


@pytest.mark.parametrize("sentence", [
    "Mentored Junior Developers and the QA Team on testing practices.",
    "Worked with Kafka Connect and Spring Boot to move data between services.",
    "Managed Payments Platform releases for the Orders Service.",
    "Trained Cross Functional Teams on CI/CD.",
])
def test_people_words_do_not_cause_false_positives(sentence):
    assert Redactor().clean(sentence) == sentence


def test_realistic_indian_it_resume_loses_only_personal_details():
    from pathlib import Path
    doc = (Path(__file__).parent / "fixtures" / "realistic_resume.txt").read_text()
    r = Redactor()
    out = r.clean(doc)
    assert r.summary() == {"email": 1, "link": 1, "phone number": 1, "name": 1}, r.summary()  # no inflated or false counts
    for gone in ("Ramesh", "Kondaveeti", "ramesh.k@gmail.com", "9876543210", "rameshbk"):
        assert gone not in out
    for kept in ("Wipro Technologies", "HCL Technologies", "Amazon Web Services", "Machine Learning", "Product Managers", "Data Scientists", "Junior Developers",
                 "Jawaharlal Nehru Technological University", "Bengaluru", "Hyderabad", "Smart India Hackathon", "Available on request", "Power BI", "Spring Boot"):
        assert kept in out, f"over-redacted: {kept}"
    assert r.restore(out) == doc


def test_repeated_first_name_is_hidden_but_counts_as_one_person():
    r = Redactor()
    out = r.clean("Priya Sharma\nExperience\nPriya led the team and Sharma's group shipped it.")
    assert "Priya" not in out and "Sharma" not in out and r.summary() == {"name": 1}
