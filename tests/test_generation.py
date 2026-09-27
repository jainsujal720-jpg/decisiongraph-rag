from decisiongraph.generation.models import (
    CitationVerdict,
    DraftClaim,
    DraftResponse,
    VerificationResponse,
)
from decisiongraph.generation.service import GroundedAnswerService
from decisiongraph.orchestration.models import EvidenceItem, RetrievalPlan, RetrievalResponse


def retrieval_response(*, evidence=True):
    items = ()
    if evidence:
        items = (
            EvidenceItem(
                "chunk:1",
                "E1",
                "atlas.md",
                "chunk-1",
                "Priya Shah owns the payment-reliability workstream.",
                ("Atlas", "Ownership"),
                (),
                ("graph", "vector_keyword"),
                1.0,
                0.9,
            ),
        )
    return RetrievalResponse(
        "Who owns payment reliability?",
        RetrievalPlan("hybrid", "Relationship plus passage detail."),
        items,
        (
            "[E1] source=atlas.md; section=Atlas > Ownership\n"
            "Priya Shah owns the payment-reliability workstream."
        ),
        20,
    )


class FakeOrchestrator:
    def __init__(self, response):
        self.response = response

    def retrieve(self, *_args):
        return self.response


class FakeAnswerModels:
    def __init__(self, draft, verification):
        self.draft_response = draft
        self.verification_response = verification

    def draft(self, *_args):
        return self.draft_response

    def verify(self, *_args):
        return self.verification_response


def test_answer_service_only_returns_verified_claims_with_citations():
    models = FakeAnswerModels(
        DraftResponse(
            claims=[DraftClaim(text="Priya Shah owns the payment-reliability workstream.", citations=["E1"])]
        ),
        VerificationResponse(
            verdicts=[
                CitationVerdict(
                    claim_index=0,
                    citation="E1",
                    supported=True,
                    reason="The evidence explicitly names Priya Shah as owner.",
                )
            ]
        ),
    )
    result = GroundedAnswerService(FakeOrchestrator(retrieval_response()), models).answer(
        "Who owns payment reliability?", "acme", "u1", ["team"], 5
    )
    assert result.decision == "answered"
    assert result.answer.endswith("[E1]")
    assert result.confidence.groundedness == 1.0
    assert result.citations[0]["source_name"] == "atlas.md"


def test_answer_service_abstains_if_a_claim_does_not_pass_verification():
    models = FakeAnswerModels(
        DraftResponse(claims=[DraftClaim(
            text="Priya Shah owns the payment-reliability workstream.", citations=["E1"])]),
        VerificationResponse(
            verdicts=[
                CitationVerdict(
                    claim_index=0,
                    citation="E1",
                    supported=False,
                    reason="Verifier rejected this claim.",
                )
            ]
        ),
    )
    result = GroundedAnswerService(FakeOrchestrator(retrieval_response()), models).answer(
        "What did Priya approve?", "acme", "u1", ["team"], 5
    )
    assert result.decision == "abstained"
    assert result.answer == "I don't have enough verified evidence to answer that safely."
    assert result.confidence.groundedness == 0.0


def test_paraphrase_is_rejected_even_if_verifier_would_have_approved_it():
    class NeverVerify(FakeAnswerModels):
        def verify(self, *_args):
            raise AssertionError("Non-verbatim claim must not reach the verifier")

    models = NeverVerify(
        DraftResponse(claims=[DraftClaim(
            text="Priya Shah owns payment reliability.", citations=["E1"]
        )]),
        VerificationResponse(),
    )
    result = GroundedAnswerService(FakeOrchestrator(retrieval_response()), models).answer(
        "Who owns payment reliability?", "acme", "u1", ["team"], 5
    )
    assert result.decision == "abstained"
    assert "verbatim" in result.claims[0].verification_reasons[0]


def test_indexing_prefix_cannot_be_quoted_as_document_text():
    item = retrieval_response().evidence[0]
    from dataclasses import replace
    prefixed = replace(item, content="Section: Atlas > Ownership\n\n" + item.content)
    assert "Priya Shah owns" in GroundedAnswerService._source_text(prefixed)
    assert "Section: Atlas" not in GroundedAnswerService._source_text(prefixed)


def test_answer_service_abstains_without_evidence_or_model_calls():
    class NeverCalled:
        def draft(self, *_args):
            raise AssertionError("draft must not run without evidence")

    result = GroundedAnswerService(
        FakeOrchestrator(retrieval_response(evidence=False)), NeverCalled()
    ).answer("Who owns payment reliability?", "acme", "u1", ["team"], 5)
    assert result.decision == "abstained"


def test_unknown_citations_are_rejected_before_verification():
    class ModelsWithUnexpectedCitation(FakeAnswerModels):
        def verify(self, *_args):
            raise AssertionError("verification must not receive an invalid-citation claim")

    models = ModelsWithUnexpectedCitation(
        DraftResponse(claims=[DraftClaim(text="Unsupported.", citations=["E99"])]),
        VerificationResponse(),
    )
    result = GroundedAnswerService(FakeOrchestrator(retrieval_response()), models).answer(
        "Question", "acme", "u1", ["team"], 5
    )
    assert result.decision == "abstained"
    assert result.claims[0].supported is False


def test_bracketed_evidence_label_is_normalized_before_verification():
    models = FakeAnswerModels(
        DraftResponse(claims=[DraftClaim(
            text="Priya Shah owns the payment-reliability workstream.",
            citations=["[E1]"],
        )]),
        VerificationResponse(verdicts=[CitationVerdict(
            claim_index=0, citation="E1", supported=True,
            reason="The cited passage directly supports the claim.",
        )]),
    )
    result = GroundedAnswerService(FakeOrchestrator(retrieval_response()), models).answer(
        "Who owns payment reliability?", "acme", "u1", ["team"], 5
    )
    assert result.decision == "answered"
    assert result.claims[0].citations == ("E1",)
    assert result.answer.endswith("[E1]")


def test_mixed_real_and_unknown_citations_are_rejected_as_one_claim():
    class ModelsWithUnexpectedCitation(FakeAnswerModels):
        def verify(self, *_args):
            raise AssertionError("verification must not receive a mixed-citation claim")

    models = ModelsWithUnexpectedCitation(
        DraftResponse(claims=[DraftClaim(text="Unsupported.", citations=["E1", "E99"])]),
        VerificationResponse(),
    )
    result = GroundedAnswerService(FakeOrchestrator(retrieval_response()), models).answer(
        "Question", "acme", "u1", ["team"], 5
    )
    assert result.decision == "abstained"
    assert result.claims[0].verification_reasons == ("Unknown citation label.",)
