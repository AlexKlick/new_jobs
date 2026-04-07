---
header-includes:
  - |
    \AtBeginDocument{\renewcommand{\maketitle}{}}
  - |
    \fancypagestyle{plain}{
      \fancyhf{}
      \renewcommand{\headrulewidth}{0pt}
      \renewcommand{\footrulewidth}{0pt}
    }
  - |
    \AtBeginDocument{\thispagestyle{plain}}
---
# Alex Klick

aklick12@gmail.com | +1-734-262-4232 | linkedin.com/in/alex-klick | Denver, CO

March 25, 2026

Hiring Team
Weaviate

When I built a RAG ingestion pipeline with sub-section-level PDF chunking for a Fortune-200 biopharma client, I learned something that shaped how I think about retrieval: precision at the chunking layer determines whether users trust the answers they get back. That project required processing tens of thousands of regulatory documents where the difference between retrieving a relevant paragraph versus a vaguely related page was the difference between a system people relied on and one they abandoned. Weaviate sits at the center of this problem for thousands of developers—building open-source infrastructure that makes retrieval systems more reliable, flexible, and easier to operate. I'm applying for engineering roles at Weaviate because this is the infrastructure work I want to contribute to.

My background aligns with what Weaviate is building in concrete ways. I've spent the past three years implementing vector databases and reranker systems in production, working primarily with pgvector and Chroma while evaluating embedding strategies across OpenAI and open-source models. I've led model-quality evaluations for sentence-transformers rerankers and deployed selected approaches at scale. My day-to-day has been in Python and TypeScript, building FastAPI backends that serve LLM-powered features to hundreds of users daily. I'm comfortable moving from ambiguous business requirements to shipped, observable systems—a pattern that defined my consulting work and one that seems relevant for a company building developer infrastructure where no two customer use cases look alike.

I should be direct about where my experience is still growing. While I've worked extensively with ML tooling—sentence-transformers, PyTorch, HuggingFace—for production retrieval and reranking, my background is in applied LLM engineering rather than ML research or model development. I also haven't worked directly with Kubernetes, though I've deployed and maintained production systems and understand containerization and orchestration for distributed infrastructure. What I bring instead is a track record of shipping reliable systems in domains where correctness matters, learning new stacks quickly, and building reusable components like the modular agent architecture I recently piloted with 100 users and expanded to 300+.

What draws me to Weaviate specifically is the open-source commitment and the work on Agent Skills, which resonates with my recent experience building modular agent components that translate user intent into structured workflows. Developers need infrastructure they can inspect, extend, and trust—especially in AI, where opacity is the default. I'd welcome the chance to discuss how my vector retrieval and production RAG experience could contribute to Weaviate's engineering team.
