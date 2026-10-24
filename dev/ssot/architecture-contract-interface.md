# Architecture contract interface design

**Selected authoring syntax: D2 (2026-10-23).** Use existing D2 syntax for new Hx
architecture sketches, with Hx interpretation of blocks, named input/output
ports, explicit connections, nested exposures, and code bindings. Arrows between
dataflow ports represent **data or signal flow**. Reuse upstream D2 parsing and
AST tooling rather than maintaining a D2 compiler fork.

The immediate scope is ordinary, individually named ports and connections.
**Buses, wide ports/signals, and bundle expansion are deferred** to the
[future plan](#future-plan-buses-and-wide-ports). Separate scalar connections may
run in opposite directions; this does not require a mixed-direction bundle.

The syntax decision is accepted. Hx metadata conventions, parser integration,
and direct ELK rendering remain **unimplemented and unverified**. The experimental
TOML contract implementation and commands are retired from the active package;
their [reference snapshot](retired-toml-contracts.md) preserves the source and
acceptance evidence. The earlier TOML input/output proposal below remains a
historical design reference, not an active or selected authoring interface.

This note records the selected direction and historical interface examples. The
retired implementation's [contract reference](retired-toml-contracts.md#archived-source)
is preserved in the archive.
The [SSOT roadmap](single-source-of-truth.md#phase-ii-architecture-authoring-and-composition-revised-direction)
records implementation status and the retained D2 experiment results.

<a id="current-implementation-service-interfaces"></a>

## Retired TOML implementation: service interfaces

The archived `hx-contract/1` format declared connectivity explicitly. This section
describes its historical behavior; the API and commands are no longer available:

```toml
# Fragment from the existing system contract
[[connections]]
from = "application.service"
to = "service.api"
```

In the [archived fixture](retired-toml-contracts.md#archived-source), the application
declared a required `Service` interface and the service component provided it.
The connection meant:

```text
application.service → service.api
       requires         provides
```

The direction identifies the requirement's implementation. It does not describe
the direction of individual argument values, results, or signals. A provided
service can receive requests and return responses through the same interface.
Consequently, `provides` is not an alias for `outputs`, and `requires` is not an
alias for `inputs`.

The archived loader also recognized parent-provided → child-provided exposures
and child-required → parent-required delegation. It checked matching logical
interface identifiers and connected child requirements. Those rules remain part
of the historical reference, not the active D2 implementation.

## Next experiment: Hx/D2 interpretation and direct ELK layout

Implement the selected D2 authoring direction through upstream parsing and Hx
architecture interpretation. The next experiment must determine how to express
Hx metadata for ordinary ports, nested exposures, and code bindings within
existing D2 syntax. It tests interpretation and rendering feasibility, not which
authoring syntax to choose. This note does not finalize the metadata conventions
or claim that stock D2 already understands Hx ports. The upstream
[D2 AST-based API](https://d2lang.com/tour/api/) is a starting point for inspecting
the available integration surface, not proof of a ready-made Hx adapter.

The proposed data flow through the tools is:

```text
D2-authored architecture + Hx interpretation
                        ↓
Hx blocks, individual ports/connections, and code bindings
                        ↓
Direct ELK layout with native ports and hierarchy
                        ↓
Hx presentation with boundary ports and code navigation
```

[ELK Layered](https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html)
documents port constraints with orthogonal routing, compound graphs, and
cross-hierarchy edges. These capabilities motivate the experiment; they do not
establish that Hx can render the required examples reliably.

This experiment deliberately relaxes the earlier requirement that **stock D2
produce all geometry**. Hx would construct a port-aware graph, request layout
directly from ELK, and present the resulting geometry. Keep the original D2 SVGs,
failed checks, and findings as evidence of that earlier experiment. The direct
ELK candidate needs its own results; it does not turn those failures into passes.

### Required demonstrations

| Case | Required result |
| --- | --- |
| Named boundary ports | Multiple ordinary inputs and outputs have visible pins on their assigned block boundaries. |
| Explicit connections | Each arrow reaches its named source/destination port. Opposite-flow connections, such as a separate ready return path, remain independent wires. |
| Nested exposure | A parent explicitly exposes individual child ports at its own boundary. Reused children retain distinct instance/port identities, including when they share a definition or code target. |
| Code navigation | Actual clicks on blocks and individual ports open the expected code target with its signature/source. |

All four cases need visible boundary pins, correct wire endpoints, readable
labels, and actual code navigation from blocks and individual ports. Initial
links may select an owning function/declaration and show its signature/source;
exact parameter or return-token highlighting remains later work. Authored
connections and code bindings do not prove runtime dataflow.

Retain the existing geometry and stability gates: pin centres on the assigned
input/output borders within two SVG units, visible wire endpoints within two
units of the declared pin outline, and no clipped/overlapping labels or routes
through unrelated blocks. Inputs and outputs keep their declared directions.
Check 100% and 150% zoom and edits that add/reorder ordinary ports,
lengthen labels, or add connections. A candidate that passes all cases must also
pass two more layout runs with stable instance/endpoint identities and topology;
pixel-identical positions are not required.

Record original inputs, interpreted ports/connections, layout output, measured
geometry, screenshots, click outcomes, and tool versions/hashes separately from
the stock-D2 reports. Missing measurements or unresolved links cannot count as a
pass. The interpretation, layout, and presentation must be demonstrated together
before selecting a production renderer or migrating authored contracts. Buses,
width-specific port handling, and bundle views are not gates for this initial
implementation.

## Future plan: buses and wide ports

Add bus and wide-port support after ordinary ports, nested exposures, and code
navigation pass their presentation gates. Keep these capabilities out of the
immediate interpretation/rendering milestone:

- Wide-port/signal width declarations, vector or lane semantics, and width labels
  such as `data[63:0]`.
- Reusable bus/bundle definitions and connections that group several named
  signals, with collapsed/expanded member views.
- Mixed-direction bundle roles and parent exposures of complete child bundles.

Retain the following demonstrations for that future phase:

| Case | Required result |
| --- | --- |
| Wide signal | One width-annotated connection represents a signal such as `data[63:0]`, with a readable label. |
| Expandable bundle | Collapsed and expanded views preserve endpoint and member-connection identities. |
| Mixed-direction handshake bundle | Data/valid flow forward and ready flows back, with member directions explicit in both views. |
| Nested bundle exposure | A parent exposes a child's bundle at its own boundary, retaining distinct instance identities and working code links, including member ports. |

These are future requirements, not accepted width/bus syntax or implemented
features. A normal value port remains in the immediate scope regardless of a
source-language scalar type's machine width; declaring width, lanes, or grouped
member connections requires the deferred support.

<a id="proposed-interface-dataflow-ports-and-wires"></a>

## Earlier TOML proposal: dataflow ports and wires

Each block declares its inputs and outputs by name. A connection between sibling
blocks names the producing output and the receiving input. Names such as `u32`
and `bool` are descriptive type labels at this stage; they do not introduce type
compatibility checks or infer program dataflow.

The following are **historical proposed TOML fragments, not accepted
`hx-contract/1` documents**. They omit a schema identifier deliberately. The
archived loader rejected the new `inputs` and `outputs` fields; that loader and
its commands have since been removed. These examples do not define a current API.

Producer declaration:

```toml
# producer.toml — proposed
name = "producer"

[inputs]
seed = "u32"

[outputs]
sample = "u32"
valid = "bool"
```

Consumer declaration:

```toml
# consumer.toml — proposed
name = "consumer"

[inputs]
sample = "u32"
valid = "bool"
```

Parent composition, using the existing child-reference shape and structured
`from`/`to` notation as the baseline within this earlier TOML proposal:

```toml
# pipeline.toml — proposed
name = "pipeline"

[[children]]
id = "producer"
contract = "producer.toml"

[[children]]
id = "consumer"
contract = "consumer.toml"

[[connections]]
from = "producer.sample"
to = "consumer.sample"

[[connections]]
from = "producer.valid"
to = "consumer.valid"
```

The intended presentation is:

```text
              ┌────────────┐                     ┌────────────┐
seed ────────▶○ Producer   ○ sample ─────────────▶○ sample     │
              │            ○ valid ──────────────▶○ valid      │
              └────────────┘                     │ Consumer   │
                                                 └────────────┘
```

The circles illustrate boundary pins. The producer's `seed` remains an externally
supplied input here; authoring a port does not imply an obligation to connect it.

### Optional arrow shorthand

D2-like arrows can be written inside ordinary TOML strings without adopting D2:

```toml
# Alternative connection notation — proposal only
connections = [
  "producer.sample -> consumer.sample",
  "producer.valid -> consumer.valid",
]
```

This array would be at the document root, before any table headers, and would
replace the structured connection records for this example. It is a possible
future convenience in that earlier design, not an implemented format. The
archived parser expected `from`/`to` records rather than strings. These retained
examples use structured records as their historical baseline; they are not plans
to restore a TOML frontend. New architecture authoring uses the selected D2
direction, whose Hx interpretation is still unimplemented.

## User-facing presentation requirements

- Multiple named inputs appear as visible pins on the left block boundary and
  named outputs on the right boundary. Labels remain readable as ports are added
  or reordered and block names become longer.
- Arrowed wires reach the named pins. Display the endpoint names and readable
  connection labels; the authoring notation does not dictate the rendering tool.
- Nested blocks can expose child inputs and outputs at their own boundary.
  Exposures must be authored explicitly rather than inferred from service-port
  roles. Their dataflow syntax needs a later implementation design.
- Reused blocks have separate instance identities even when they share a
  definition or code target. Connections address the appropriate instance's port.
- Blocks and ports support code navigation. Future explicit bindings may associate
  ports with parameters, return values, or hardware signals. Initial links may
  open the owning function or declaration; exact token highlighting is separate
  work. Port declarations alone do not establish these bindings.

Authoring and rendering are separate decisions. The
[D2 experiment](../d2_ports_experiment/README.md) failed the boundary-pin gate in
all tested profiles. Keep its evidence and presentation acceptance criteria.
The next Hx/D2 interpretation and direct ELK experiment must demonstrate ordinary
ports, explicit connections, nested scalar exposures, and code navigation itself.
Bus/width handling and bundle views belong to the future plan above.

## Compatibility and implementation boundary

The TOML service-contract APIs, commands, schemas, tests, and public documentation
have been retired without compatibility stubs. Existing extraction, saved graphs,
annotations, project configuration, and viewer behavior retain their current
interfaces. There is no automatic conversion of archived TOML contracts into D2.
Future dataflow connections must have their own explicit meaning rather than
silently reinterpreting the old service dependencies.

Projection's evidence-reconciliation ideas remain preserved with their original
TOML loader and service-model dependencies. Reuse relevant parts when D2 needs
implementation bindings; no generic projection backend is introduced now.

Further type compatibility checks, required-connection checks, behavioral
obligations, conformance evaluation, native-test evidence ingestion, and testcase
generation are deferred. Describing a wire is authored intent, not proof that
parsed code transfers a value along that wire. Archived service-composition
validation describes the retired prototype only.

This change records the accepted D2 syntax decision and staged implementation
scope. A later implementation plan must define D2/Hx metadata conventions,
upstream parser access, ELK integration, ordinary-port exposures, and code-binding
details before changing parsers or viewer behavior. Direct ELK is the next layout
candidate to test; it is not a verified production renderer. No new parser,
public API, or automatic TOML migration is introduced by this documentation
amendment.
