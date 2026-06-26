# ADR-002: Use LangGraph Instead of a Custom Agent Loop

## Status
Accepted

## Context
The review agent needs to execute a multi-step pipeline: parse diff → fetch context → build prompt → call LLM → parse response → post comments. This could be implemented as a plain Python function calling each step sequentially.

The question was whether to introduce LangGraph (a graph-based agent framework) or keep a simple imperative loop.

## Decision
Use **LangGraph** to model the agent as an explicit state machine with named nodes and typed state transitions.

## Consequences

**Gained:**
- Each node (`diff_parser`, `context_fetcher`, `prompt_builder`, etc.) is independently testable — you can unit test a node by passing it a state dict and asserting the output
- State is an explicit typed dict, not implicit function arguments — easier to inspect and log at each step
- Conditional edges make branching logic (e.g., skip context fetch for small diffs) readable and auditable
- LangGraph's built-in streaming allows per-node progress events — useful for the future dashboard
- Signals familiarity with the modern agent framework ecosystem to reviewers

**Trade-offs:**
- Adds a dependency (`langgraph`) for what could be a 50-line sequential function
- Learning curve for contributors unfamiliar with graph-based agents
- Slight overhead from state serialization between nodes

**Why not LangChain LCEL or a plain chain?**
LCEL chains are linear. The review pipeline has conditional paths (retry on parse failure, skip hunks below a size threshold) that are cleaner to express as graph edges than nested conditionals inside a chain.

**Mitigation:**
`docs/architecture.md` includes a visual of the graph with node descriptions so contributors can understand the flow without reading LangGraph docs first.
