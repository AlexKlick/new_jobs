# Alex Klick



## Opening

Last year, I helped a Fortune-200 biopharma client cut weeks off their regulatory submission timeline by building a RAG ingestion pipeline that could parse complex PDF documents at sub-section granularity and retrieve precisely the context their reviewers needed. That project—a system handling tens of thousands of documents with vector search and reranking—taught me that retrieval architecture directly translates to time saved and trust earned in high-consequence domains. When I saw Webflow's Staff Software Engineer, Applied AI role, the alignment struck me: you're building AI features that empower designers and marketers to create without friction, and the engineering challenges—grounding outputs, scaling retrieval, making AI feel like a natural extension of the tool—mirror exactly the problems I've been solving in enterprise contexts.

## Role Alignment

My background sits at the intersection of production AI systems and backend engineering, which maps closely to what this role demands. At Credera, I've spent the last three years designing and deploying vector database and reranker systems, building LLM-powered document intelligence pipelines, and iterating on agentic architectures that translate user intent into structured outputs. I've worked directly with the stack this role emphasizes: OpenAI API and embeddings for retrieval, pgvector and Chroma for vector storage, sentence-transformers rerankers for result quality, and LangChain/Agents SDK for orchestrating multi-step workflows. While the role mentions React and Node.js specifically, my TypeScript experience and Python backend fluency give me strong transferable foundations—I've shipped production systems in TypeScript and understand the component-model thinking that React requires. I'm genuinely excited to bring that backend depth to a frontend-adjacent role where I can contribute to AI features that ship to millions of Webflow users.

## Evidence Highlights

The project I'm most proud of is the document ingestion pipeline I architected for the biopharma client. We needed to process PDFs containing clinical tables embedded in RTF format, chunk them at precise sub-section levels, and serve those chunks through a vector search system that could answer regulatory queries accurately. I designed the chunking strategy, implemented the reranking layer using sentence-transformers, and led the quality analysis that selected the model we deployed at scale. The result: a system that cut document review time from weeks to days for reviewers who previously had to read linearly. Another example is the enterprise chat tooling I built for Credera's internal teams—a vector search and reranker system serving hundreds of consultants daily, with retrieval quality that actually got better over time as we tuned the reranking model. I've also mentored three junior engineers on agentic workflow reliability, teaching them to think about chunking strategies, embedding quality, and reranker selection as interconnected levers for user outcomes.

## Closing

What draws me to Webflow specifically is the scale of the platform—you're enabling millions of people to build without code, and AI features that feel invisible and helpful in that context could reshape how people create on the web. I'd love to bring my production RAG experience, my comfort with ambiguous requirements in regulated environments, and my belief that retrieval quality and user trust are the same problem to your team. Let's talk about how I can contribute to the AI features shaping Webflow's next chapter.
