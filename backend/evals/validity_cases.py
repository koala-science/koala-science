"""Labelled arguments for the `validity` check.

Same paper and tiers as ``relevance_cases`` — see that module and README.md. The
cases lean on the two arms that are easiest to get wrong in either direction:
coherence, where a chained claim must pass and a bundled one must fail, and
self-containment, where a located point must pass and a bare pointer, an
acronym or a name the paper coined must fail.
"""
from evals.relevance_cases import Case


CASES: list[Case] = [
    # ---- passes -------------------------------------------------------------
    Case("chained-baseline", "negative",
         "The baseline is missing, and previous papers have shown that it is quite "
         "hard to beat.",
         "Doe et al. (2020) have shown that the baseline X is simple and extremely "
         "hard to beat. In fact, the community has adopted this baseline, as seen "
         "in K et al. and J et al.",
         True, "anchor", "the constitution's passing example: chained, not bundled"),
    Case("no-retrieval-baseline", "negative",
         "The evaluation omits a no-retrieval baseline, so the reported gain cannot "
         "be attributed to retrieval.",
         "Table 2 compares only retrieval variants; Section 4.1 never reports a "
         "closed-book configuration of the same reasoner.",
         True, "anchor", "one point, stated plainly, locatable evidence"),
    Case("located-pointer", "negative",
         "The 0.4-point gain in Table 3 sits inside the 0.6-point seed standard "
         "deviation the authors report, so it is not statistically meaningful.",
         "Table 3 reports 71.4 against 71.0 for the strongest baseline, and "
         "Appendix B gives a standard deviation of 0.6 across five seeds.",
         True, "clear", "a pointer that locates a stated point is fine"),
    Case("defined-acronym", "negative",
         "The low-rank adaptation (LoRA) variant is never compared against full "
         "fine-tuning, so the claimed efficiency gain is untested.",
         "Table 5 lists only LoRA configurations; Section 4.3 claims the method is "
         "cheaper than full fine-tuning without reporting it.",
         True, "edge", "an acronym defined where it is used"),
    Case("described-not-named", "positive",
         "The paper's new benchmark fills a real gap: it is the first multi-hop "
         "question-answering benchmark built over primary scientific sources.",
         "Section 3 describes 12k questions derived from paper full texts; the "
         "closest prior benchmark, HotpotQA, is built from Wikipedia.",
         True, "clear", "praise that describes the paper's artifact rather than naming it"),
    Case("same-problem-many-places", "negative",
         "Every results table reports single runs without variance, so none of the "
         "comparisons can be judged against noise.",
         "Tables 2, 3 and 4 each give one number per system; Section 4 never states "
         "a number of seeds.",
         True, "clear", "several instances of one problem is one point"),
    Case("compound-dependent", "negative",
         "The contrastive objective is trained with a larger batch than the "
         "baselines, which could explain the whole reported gain.",
         "Section 3.3 uses a batch of 4096 for the proposed objective; Table 4's "
         "baselines use 512.",
         True, "clear", "second half depends on the first"),

    # ---- fails --------------------------------------------------------------
    Case("bundled-no-evidence", "negative",
         "The baseline is missing and the dataset is too small.",
         "There is no need for evidence, as this is clear from the manuscript.",
         False, "anchor", "the constitution's failing example: two points, no evidence"),
    Case("bundled-praise", "positive",
         "The ablation is thorough and the writing is clear.",
         "Table 4 ablates every component; Section 3 walks through a worked example.",
         False, "clear", "two independent pieces of praise"),
    Case("undefined-acronym", "negative",
         "The OOD results undermine the KD claim.",
         "Table 5 shows a 9-point drop on the out-of-distribution split, while the "
         "abstract claims knowledge distillation preserves robustness.",
         False, "anchor", "field-specific acronyms a reader of the claim alone cannot expand"),
    Case("coined-name", "negative",
         "RARE collapses on MultiSciQA's hardest split.",
         "Table 5 reports 31.2 exact match on the 4-hop split against 58.9 overall.",
         False, "clear", "names the paper coined, used as if the reader knows them"),
    Case("bare-pointer", "negative",
         "The results in Table 3 are wrong.",
         "Table 3 reports 71.2 for the proposed method, but Section 4.1 states 69.8 "
         "for the same configuration.",
         False, "clear", "the point lives in the evidence, not the claim"),
    Case("vague-thesis", "negative",
         "The evaluation is not convincing.",
         "Table 2 reports single runs; Section 4.1 omits a closed-book baseline; "
         "the benchmark was built by the authors.",
         False, "clear", "no intuition about what the evidence will show"),
    Case("common-acronym", "negative",
         "Training the model needs 64 GPUs, which puts replication out of reach "
         "for most academic groups.",
         "Section 4 reports training on 64 A100 GPUs for 11 days.",
         True, "edge", "a universally known acronym is allowed"),
    Case("neutral-summary", "negative",
         "The paper evaluates its method on three question-answering benchmarks.",
         "Section 4 reports results on SciFact, HotpotQA and a new benchmark.",
         False, "clear", "a description, not a judgement"),
    Case("wrong-position", "positive",
         "The evaluation omits a no-retrieval baseline, so the reported gain cannot "
         "be attributed to retrieval.",
         "Table 2 compares only retrieval variants; Section 4.1 never reports a "
         "closed-book configuration of the same reasoner.",
         False, "edge", "criticism labelled as praise"),
    Case("open-question", "negative",
         "It would be interesting to know whether the method scales to longer "
         "reasoning chains.",
         "Section 4 only evaluates questions of two to four hops.",
         False, "edge", "wondering, not taking a side"),
    Case("opinion-evidence", "negative",
         "The retrieval depth is never justified, which leaves the main gain open "
         "to tuning on the test set.",
         "This is obvious to anyone who reads the paper carefully.",
         False, "clear", "evidence is opinion"),
    Case("unrelated-evidence", "negative",
         "The contrastive objective is not novel: it matches an earlier published "
         "objective up to notation.",
         "Table 2 reports single runs with no variance.",
         False, "clear", "evidence about something else"),
]
