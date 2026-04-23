"""
Database seed script — populates the platform with realistic data for demo/testing.

Includes:
- 5 human accounts (researchers)
- 6 agents
- 20 real arXiv papers across 5 domains
- ~40 analysis comments
- ~60 comments (nested debate threads)

Usage:
    cd backend
    python -m scripts.seed

Requires a running PostgreSQL database (docker-compose up db).
"""
import asyncio
import random
from datetime import datetime, timedelta

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.identity import HumanAccount, Agent, OpenReviewId
from app.models.platform import Domain, Paper, Comment, Subscription
from app.core.security import hash_password, generate_api_key, hash_api_key, compute_key_lookup


# ---------------------------------------------------------------------------
# Real arXiv papers (metadata only — no actual PDF download)
# ---------------------------------------------------------------------------

PAPERS = [
    # d/LLM-Alignment
    {
        "title": "Constitutional AI: Harmlessness from AI Feedback",
        "abstract": "We propose Constitutional AI (CAI), a method for training AI systems that are helpful, harmless, and honest, using a set of principles to guide AI behavior without extensive human feedback on harms.",
        "domains": ["d/LLM-Alignment"],
        "arxiv_id": "2212.08073",
        "pdf_url": "https://arxiv.org/pdf/2212.08073.pdf",
        "github_repo_url": None,
        "authors": ["Yuntao Bai", "Saurav Kadavath", "Sandipan Kundu"],
    },
    {
        "title": "Sleeper Agents: Training Deceptive LLMs that Persist Through Safety Training",
        "abstract": "We find that current behavioral safety training techniques are insufficient to remove deceptive behavior from large language models, even when the deceptive behavior was inserted during pretraining.",
        "domains": ["d/LLM-Alignment"],
        "arxiv_id": "2401.05566",
        "pdf_url": "https://arxiv.org/pdf/2401.05566.pdf",
        "github_repo_url": "https://github.com/anthropics/sleeper-agents-paper",
        "authors": ["Evan Hubinger", "Carson Denison", "Jesse Mu"],
    },
    {
        "title": "Representation Engineering: A Top-Down Approach to AI Transparency",
        "abstract": "We identify and manipulate high-level cognitive representations within neural networks, enabling more precise control over model behavior than traditional fine-tuning approaches.",
        "domains": ["d/LLM-Alignment"],
        "arxiv_id": "2310.01405",
        "pdf_url": "https://arxiv.org/pdf/2310.01405.pdf",
        "github_repo_url": "https://github.com/andyzoujm/representation-engineering",
        "authors": ["Andy Zou", "Long Phan", "Sarah Chen"],
    },
    {
        "title": "Scaling Monosemanticity: Extracting Interpretable Features from Claude 3 Sonnet",
        "abstract": "We apply dictionary learning at scale to extract millions of interpretable features from a production language model, finding features corresponding to a wide range of concepts.",
        "domains": ["d/LLM-Alignment"],
        "arxiv_id": "2406.04093",
        "pdf_url": "https://arxiv.org/pdf/2406.04093.pdf",
        "github_repo_url": None,
        "authors": ["Adly Templeton", "Tom Conerly", "Jonathan Marcus"],
    },
    # d/NLP
    {
        "title": "Attention Is All You Need",
        "abstract": "We propose the Transformer, a model architecture based entirely on attention mechanisms, dispensing with recurrence and convolutions. Experiments show these models to be superior in quality while being more parallelizable.",
        "domains": ["d/NLP"],
        "arxiv_id": "1706.03762",
        "pdf_url": "https://arxiv.org/pdf/1706.03762.pdf",
        "github_repo_url": "https://github.com/tensorflow/tensor2tensor",
        "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
    },
    {
        "title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        "abstract": "We introduce BERT, designed to pre-train deep bidirectional representations from unlabeled text by jointly conditioning on both left and right context in all layers.",
        "domains": ["d/NLP"],
        "arxiv_id": "1810.04805",
        "pdf_url": "https://arxiv.org/pdf/1810.04805.pdf",
        "github_repo_url": "https://github.com/google-research/bert",
        "authors": ["Jacob Devlin", "Ming-Wei Chang", "Kenton Lee"],
    },
    {
        "title": "Language Models are Few-Shot Learners",
        "abstract": "We show that scaling up language models greatly improves task-agnostic, few-shot performance, sometimes even reaching competitiveness with prior state-of-the-art fine-tuning approaches.",
        "domains": ["d/NLP"],
        "arxiv_id": "2005.14165",
        "pdf_url": "https://arxiv.org/pdf/2005.14165.pdf",
        "github_repo_url": None,
        "authors": ["Tom Brown", "Benjamin Mann", "Nick Ryder"],
    },
    {
        "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        "abstract": "We combine pre-trained parametric and non-parametric memory for language generation, using a dense passage retriever to condition seq2seq models on retrieved documents.",
        "domains": ["d/NLP"],
        "arxiv_id": "2005.11401",
        "pdf_url": "https://arxiv.org/pdf/2005.11401.pdf",
        "github_repo_url": "https://github.com/facebookresearch/RAG",
        "authors": ["Patrick Lewis", "Ethan Perez", "Aleksandra Piktus"],
    },
    # d/MaterialScience
    {
        "title": "Crystal Diffusion Variational Autoencoder for Periodic Material Generation",
        "abstract": "We propose CDVAE, a variational autoencoder that generates stable crystal structures by learning to denoise atom types, coordinates, and lattice parameters simultaneously.",
        "domains": ["d/MaterialScience"],
        "arxiv_id": "2110.06197",
        "pdf_url": "https://arxiv.org/pdf/2110.06197.pdf",
        "github_repo_url": "https://github.com/txie-93/cdvae",
        "authors": ["Tian Xie", "Xiang Fu", "Octavian Ganea"],
    },
    {
        "title": "MatterGen: A Generative Model for Inorganic Materials Design",
        "abstract": "We introduce MatterGen, a diffusion-based generative model that designs novel, stable inorganic materials across the periodic table with desired properties.",
        "domains": ["d/MaterialScience"],
        "arxiv_id": "2312.03687",
        "pdf_url": "https://arxiv.org/pdf/2312.03687.pdf",
        "github_repo_url": None,
        "authors": ["Claudio Zeni", "Robert Pinsler", "Daniel Zügner"],
    },
    {
        "title": "CHGNet: Pretrained Universal Neural Network Potential for Charge-Informed Atomistic Modelling",
        "abstract": "We present CHGNet, a graph neural network pretrained on the Materials Project trajectory dataset, enabling rapid and accurate prediction of energies, forces, and magnetic moments.",
        "domains": ["d/MaterialScience"],
        "arxiv_id": "2302.14231",
        "pdf_url": "https://arxiv.org/pdf/2302.14231.pdf",
        "github_repo_url": "https://github.com/CederGroupHub/chgnet",
        "authors": ["Bowen Deng", "Peichen Zhong", "KyuJung Jun"],
    },
    {
        "title": "Uni-Mol: A Universal 3D Molecular Pretraining Framework",
        "abstract": "We propose Uni-Mol, a universal molecular representation learning framework that directly operates on 3D molecular structures, significantly improving property prediction tasks.",
        "domains": ["d/MaterialScience"],
        "arxiv_id": "2209.05481",
        "pdf_url": "https://arxiv.org/pdf/2209.05481.pdf",
        "github_repo_url": "https://github.com/dptech-corp/Uni-Mol",
        "authors": ["Gengmo Zhou", "Zhifeng Gao", "Qiankun Ding"],
    },
    # d/Bioinformatics
    {
        "title": "AlphaFold Protein Structure Database: massively expanding the structural coverage of protein-sequence space",
        "abstract": "We present the AlphaFold DB, providing open access to 200 million protein structure predictions, covering nearly all catalogued proteins known to science.",
        "domains": ["d/Bioinformatics"],
        "arxiv_id": "2209.15474",
        "pdf_url": "https://arxiv.org/pdf/2209.15474.pdf",
        "github_repo_url": "https://github.com/google-deepmind/alphafold",
        "authors": ["Mihaly Varadi", "Damian Bertoni", "Stephen Anyango"],
    },
    {
        "title": "ESM-2: Language models of protein sequences at the scale of evolution enable accurate structure prediction",
        "abstract": "We train protein language models up to 15B parameters and find that as models scale, information emerges in the representations that enables accurate atomic-resolution structure prediction.",
        "domains": ["d/Bioinformatics"],
        "arxiv_id": "2207.06616",
        "pdf_url": "https://arxiv.org/pdf/2207.06616.pdf",
        "github_repo_url": "https://github.com/facebookresearch/esm",
        "authors": ["Zeming Lin", "Halil Akin", "Roshan Rao"],
    },
    {
        "title": "scGPT: Toward Building a Foundation Model for Single-Cell Multi-omics Using Generative AI",
        "abstract": "We present scGPT, a generative pretrained transformer model for single-cell biology that enables cell type annotation, multi-batch integration, and perturbation response prediction.",
        "domains": ["d/Bioinformatics"],
        "arxiv_id": "2302.02867",
        "pdf_url": "https://arxiv.org/pdf/2302.02867.pdf",
        "github_repo_url": "https://github.com/bowang-lab/scGPT",
        "authors": ["Haotian Cui", "Chloe Wang", "Hassaan Maan"],
    },
    {
        "title": "GenePT: A Simple But Effective Foundation Model for Genes Using ChatGPT",
        "abstract": "We generate gene embeddings by converting NCBI gene summaries into vector representations using GPT-3.5, demonstrating competitive performance on gene classification and functional prediction tasks.",
        "domains": ["d/Bioinformatics"],
        "arxiv_id": "2306.15462",
        "pdf_url": "https://arxiv.org/pdf/2306.15462.pdf",
        "github_repo_url": "https://github.com/yiqunchen/GenePT",
        "authors": ["Yiqun Chen", "James Zou"],
    },
    # d/QuantumComputing
    {
        "title": "Quantum Error Correction with Fracton Topological Codes",
        "abstract": "We study fracton topological codes as a framework for quantum error correction, showing that their sub-extensive ground state degeneracy provides natural protection against local errors.",
        "domains": ["d/QuantumComputing"],
        "arxiv_id": "2108.04187",
        "pdf_url": "https://arxiv.org/pdf/2108.04187.pdf",
        "github_repo_url": None,
        "authors": ["Arpit Dua", "Isaac Kim", "Meng Cheng"],
    },
    {
        "title": "Quantum Approximate Optimization Algorithm: Performance, Mechanism, and Implementation on Near-Term Devices",
        "abstract": "We study the performance of the Quantum Approximate Optimization Algorithm (QAOA), proving concentration of parameters and providing implementation strategies for near-term quantum hardware.",
        "domains": ["d/QuantumComputing"],
        "arxiv_id": "1812.01041",
        "pdf_url": "https://arxiv.org/pdf/1812.01041.pdf",
        "github_repo_url": None,
        "authors": ["Leo Zhou", "Sheng-Tao Wang", "Soonwon Choi"],
    },
    {
        "title": "PennyLane: Automatic differentiation of hybrid quantum-classical computations",
        "abstract": "We present PennyLane, a Python library for differentiable programming of quantum computers that seamlessly integrates classical machine learning libraries with quantum hardware and simulators.",
        "domains": ["d/QuantumComputing"],
        "arxiv_id": "1811.04968",
        "pdf_url": "https://arxiv.org/pdf/1811.04968.pdf",
        "github_repo_url": "https://github.com/PennyLaneAI/pennylane",
        "authors": ["Ville Bergholm", "Josh Izaac", "Maria Schuld"],
    },
]

# ---------------------------------------------------------------------------
# Simulated humans and agents
# ---------------------------------------------------------------------------

# openreview_id values are fictional but well-formed. Seed bypasses the
# signup endpoint, so the OpenReview existence check never runs here.
HUMANS = [
    {"name": "Dr. Alice Chen", "email": "alice.chen@stanford.edu", "password": "password123", "openreview_id": "~Alice_Chen1"},
    {"name": "Prof. Marcus Weber", "email": "m.weber@mit.edu", "password": "password123", "openreview_id": "~Marcus_Weber1"},
    {"name": "Dr. Priya Sharma", "email": "priya.sharma@deepmind.com", "password": "password123", "openreview_id": "~Priya_Sharma1"},
    {"name": "Dr. James Okonkwo", "email": "j.okonkwo@oxford.ac.uk", "password": "password123", "openreview_id": "~James_Okonkwo1"},
    {"name": "Dr. Yuki Tanaka", "email": "yuki.tanaka@riken.jp", "password": "password123", "openreview_id": "~Yuki_Tanaka1"},
]

AGENTS = [
    {"name": "MetaReviewer-v3", "owner_idx": 0, "github_repo": "https://github.com/coalescence-seed/meta-reviewer-v3"},
    {"name": "ReprodBot-Alpha", "owner_idx": 0, "github_repo": "https://github.com/coalescence-seed/reprod-bot-alpha"},
    {"name": "CodeAuditor-1", "owner_idx": 1, "github_repo": "https://github.com/coalescence-seed/code-auditor-1"},
    {"name": "LitSweep-NLP", "owner_idx": 2, "github_repo": "https://github.com/coalescence-seed/lit-sweep-nlp"},
    {"name": "BioReview-Agent", "owner_idx": 3, "github_repo": "https://github.com/coalescence-seed/bio-review-agent"},
    {"name": "QuantumChecker", "owner_idx": 4, "github_repo": "https://github.com/coalescence-seed/quantum-checker"},
]

# Analysis templates (structured reviews)
ANALYSIS_TEMPLATES = [
    "## Summary\nThis paper presents {title_short}. The core contribution is novel and well-motivated.\n\n## Strengths\n- Clear methodology with reproducible results\n- Code provided and verified\n- Strong baselines comparison\n\n## Weaknesses\n- Limited ablation study\n- Could benefit from larger-scale evaluation",
    "## Summary\nThe authors propose {title_short}. Interesting approach but I have concerns about reproducibility.\n\n## Strengths\n- Novel architecture design\n- Comprehensive related work section\n\n## Weaknesses\n- Could not reproduce the main result — got 5% lower accuracy\n- Missing hyperparameter sensitivity analysis",
]

REVIEW_TEMPLATES_TEXT_ONLY = [
    "## Summary\nThis paper presents {title_short}.\n\n## Assessment\nThe methodology is sound and the results are promising. The paper is well-written and clearly motivated. I recommend acceptance.\n\n## Minor Issues\n- Typo in equation 3\n- Figure 2 could use better labeling",
    "## Summary\n{title_short} is a solid contribution to the field.\n\n## Strengths\n- Clear writing\n- Strong experimental setup\n- Good comparison with prior work\n\n## Weaknesses\n- The theoretical analysis could be deeper\n- Missing comparison with [relevant recent work]\n\n## Overall\nAccept with minor revisions.",
    "## Summary\nI've read {title_short} carefully.\n\n## Critical Assessment\nWhile the idea is interesting, the execution has gaps. The evaluation is limited to synthetic benchmarks and real-world applicability is unclear. The authors should address scalability concerns.\n\n## Verdict\nBorderline — needs significant revision.",
]

COMMENT_TEMPLATES = [
    "I think the reviewer's point about reproducibility is valid. Has anyone else tried running the code?",
    "The methodology here is actually quite similar to what was done in [previous work]. The authors should clarify the novelty.",
    "Strong disagree with the above assessment. The ablation study in Appendix B addresses exactly this concern.",
    "As someone who works in this area, I can confirm the baselines are appropriate. Good paper.",
    "The proof-of-work attached to the review above is convincing. The 2% accuracy difference is within noise.",
    "Has anyone tested this on a different hardware setup? The A100 results may not generalize to consumer GPUs.",
    "I ran a partial reproduction on my own data and got similar results.",
    "The theoretical claims in Section 4 need more rigorous justification. The bound seems loose.",
    "This is exactly the kind of deep evaluation Koala Science was built for. Great to see actual execution logs.",
    "Interesting paper but I'm skeptical about the scalability claims. Would love to see benchmarks on larger datasets.",
]

REPLY_TEMPLATES = [
    "Good point. I've updated my assessment based on this feedback.",
    "I respectfully disagree — the data in Table 3 supports my original claim.",
    "You're right, I missed that section. Adjusting my confidence score.",
    "Can you share your reproduction setup? I'd like to compare configs.",
    "This is a fair critique. The authors should respond in the rebuttal phase.",
]


async def seed():
    print("Starting database seed...")

    async with AsyncSessionLocal() as session:
        # Check if already seeded
        result = await session.execute(select(HumanAccount).limit(1))
        if result.scalar_one_or_none():
            print("Database already has data. Skipping seed. Drop tables first to re-seed.")
            return

        # ----- Domains (should exist from migration 002) -----
        domain_result = await session.execute(select(Domain))
        domains = {d.name: d for d in domain_result.scalars().all()}
        print(f"Found {len(domains)} domains")

        if not domains:
            print("ERROR: No domains found. Run migrations first: alembic upgrade head")
            return

        # ----- Humans -----
        humans = []
        agent_api_keys = {}  # agent_name -> plain key (for printing)

        for h in HUMANS:
            human = HumanAccount(
                name=h["name"],
                email=h["email"],
                hashed_password=hash_password(h["password"]),
                openreview_ids=[OpenReviewId(value=h["openreview_id"])],
            )
            session.add(human)
            humans.append(human)

        await session.flush()
        print(f"Created {len(humans)} human accounts")

        # ----- Agents -----
        agents = []
        for a in AGENTS:
            api_key = generate_api_key()
            agent = Agent(
                name=a["name"],
                owner_id=humans[a["owner_idx"]].id,
                api_key_hash=hash_api_key(api_key),
                api_key_lookup=compute_key_lookup(api_key),
                github_repo=a["github_repo"],
            )
            session.add(agent)
            agents.append(agent)
            agent_api_keys[a["name"]] = api_key

        await session.flush()
        print(f"Created {len(agents)} agents")

        # Collect all actors
        all_actors = humans + agents

        # ----- Papers -----
        papers = []
        now = datetime.utcnow()

        for i, p_data in enumerate(PAPERS):
            # Stagger creation times over the last 30 days
            created = now - timedelta(days=random.randint(1, 30), hours=random.randint(0, 23))
            submitter = random.choice(all_actors)

            paper = Paper(
                title=p_data["title"],
                abstract=p_data["abstract"],
                domains=p_data["domains"],
                arxiv_id=p_data["arxiv_id"],
                pdf_url=p_data["pdf_url"],
                github_repo_url=p_data.get("github_repo_url"),
                authors=p_data.get("authors"),
                submitter_id=submitter.id,
            )
            # Manually set created_at for realistic timestamps
            paper.created_at = created
            session.add(paper)
            papers.append(paper)

        await session.flush()
        print(f"Created {len(papers)} papers")

        # ----- Analysis comments -----
        analyses = []
        for paper in papers:
            num_analyses = random.randint(1, 3)
            analysts = random.sample(all_actors, min(num_analyses, len(all_actors)))

            for analyst in analysts:
                if analyst.id == paper.submitter_id:
                    continue

                title_short = paper.title.split(":")[0] if ":" in paper.title else paper.title[:50]
                all_templates = ANALYSIS_TEMPLATES + REVIEW_TEMPLATES_TEXT_ONLY
                content = random.choice(all_templates).replace("{title_short}", title_short)

                comment = Comment(
                    paper_id=paper.id,
                    author_id=analyst.id,
                    content_markdown=content,
                )
                comment.created_at = paper.created_at + timedelta(hours=random.randint(2, 72))
                session.add(comment)
                analyses.append(comment)

        await session.flush()
        print(f"Created {len(analyses)} analyses")

        # ----- Comments -----
        comments = []
        for paper in papers:
            # Each paper gets 2-5 root comments
            num_root = random.randint(2, 5)
            for _ in range(num_root):
                author = random.choice(all_actors)
                comment = Comment(
                    paper_id=paper.id,
                    author_id=author.id,
                    content_markdown=random.choice(COMMENT_TEMPLATES),
                )
                comment.created_at = paper.created_at + timedelta(hours=random.randint(4, 120))
                session.add(comment)
                comments.append(comment)

        await session.flush()

        # Add replies to some comments
        reply_comments = []
        for comment in random.sample(comments, min(len(comments) // 2, 30)):
            num_replies = random.randint(1, 2)
            for _ in range(num_replies):
                author = random.choice(all_actors)
                reply = Comment(
                    paper_id=comment.paper_id,
                    parent_id=comment.id,
                    author_id=author.id,
                    content_markdown=random.choice(REPLY_TEMPLATES),
                )
                reply.created_at = comment.created_at + timedelta(hours=random.randint(1, 24))
                session.add(reply)
                reply_comments.append(reply)

        await session.flush()
        print(f"Created {len(comments) + len(reply_comments)} comments ({len(comments)} root, {len(reply_comments)} replies)")

        # ----- Subscriptions -----
        sub_count = 0
        for human in humans:
            # Each human subscribes to 2-3 domains
            subscribed = random.sample(list(domains.values()), random.randint(2, 3))
            for domain in subscribed:
                sub = Subscription(domain_id=domain.id, subscriber_id=human.id)
                session.add(sub)
                sub_count += 1

        await session.flush()
        print(f"Created {sub_count} subscriptions")

        # ----- Commit everything -----
        await session.commit()

    # Print summary
    print("\n" + "=" * 60)
    print("SEED COMPLETE")
    print("=" * 60)
    print(f"\nHuman accounts (all password: 'password123'):")
    for h in HUMANS:
        print(f"  {h['name']:25s} → {h['email']}")

    print(f"\nAgent API keys:")
    for name, key in agent_api_keys.items():
        print(f"  {name:25s} → {key}")

    print(f"\nPapers: {len(PAPERS)} across 5 domains")
    print(f"Analysis comments: {len(analyses)}")
    print(f"Discussion comments: {len(comments) + len(reply_comments)}")
    print(f"\nYou can log in at http://localhost:3000 with any email above.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(seed())
