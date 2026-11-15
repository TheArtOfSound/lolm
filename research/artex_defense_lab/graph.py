"""Provenance-preserving, deterministic evidence graph for offline security analysis.

No tool calls, code evaluation, external IO, or authority delegation. Only parsed
Event records may be inserted. Observations are immutable evidence, not directives.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib
import json
from .core import Event


def _id(kind: str, case: str, value: str) -> str:
    # Case-scoped IDs prevent accidental joins and avoid raw IDs in node keys.
    # Unkeyed hashes are NOT a privacy/anonymization guarantee.
    return kind + ':' + hashlib.sha256(json.dumps([case, value], separators=(',', ':')).encode()).hexdigest()[:24]

@dataclass(frozen=True, order=True)
class Node:
    id: str
    kind: str
    event_id: str = ''
    minute: int = 0

@dataclass(frozen=True, order=True)
class Edge:
    from_id: str
    to_id: str
    kind: str
    proof_event_id: str

class EvidenceGraph:
    """Untrusted text never becomes node/edge names or commands.

    Nodes contain only typed hashed identifiers. Edges connect events to a
    case-local principal, device, behavior, and the last prior event.
    """
    def __init__(self, max_nodes: int = 20000):
        if type(max_nodes) is not int or not 1 <= max_nodes <= 1_000_000:
            raise ValueError('invalid graph size bound')
        self.max_nodes = max_nodes
        self.nodes: dict[str, Node] = {}
        self.edges: set[Edge] = set()
        self._event_index: dict[tuple[str,str], str] = {}
        self._prior_by_identity: dict[tuple[str,str], tuple[str, int]] = {}

    def add(self, event: Event) -> str:
        if not isinstance(event, Event):
            raise TypeError('graph accepts validated Event objects only')
        event_key = (event.case_id,event.event_id)
        if event_key in self._event_index:
            raise ValueError('repeated event in graph')
        e_id = _id('event',event.case_id,event.event_id)
        p_id = _id('principal',event.case_id,event.identity)
        d_id = _id('device',event.case_id,event.device)
        b_id = _id('behavior',event.case_id,event.kind)
        candidates = (Node(e_id,'event',event.event_id,event.minute),Node(p_id,'principal'),
                      Node(d_id,'device'),Node(b_id,'behavior'))
        new_ids = {node.id for node in candidates if node.id not in self.nodes}
        if len(self.nodes) + len(new_ids) > self.max_nodes:
            raise ValueError('graph capacity exceeded; refusing to mutate evidence')
        for node in candidates:
            self.nodes[node.id] = node
        self.edges.add(Edge(p_id,e_id,'principal_observed',event.event_id))
        self.edges.add(Edge(e_id,d_id,'observed_on_device',event.event_id))
        self.edges.add(Edge(e_id,b_id,'behavior_kind',event.event_id))
        prior_key = (event.case_id,event.identity)
        previous = self._prior_by_identity.get(prior_key)
        if previous and previous[1] <= event.minute:
            self.edges.add(Edge(previous[0],e_id,'followed_by',event.event_id))
        self._prior_by_identity[prior_key] = (e_id,event.minute)
        self._event_index[event_key] = e_id
        return e_id

    @classmethod
    def from_events(cls, events: list[Event], max_nodes: int = 20000) -> 'EvidenceGraph':
        graph = cls(max_nodes)
        for event in sorted(events,key=lambda x:(x.case_id,x.minute,x.event_id)):
            graph.add(event)
        return graph

    def evidence_subgraph(self, case_id: str, event_ids: list[str]) -> dict:
        """Only reveal node IDs connected to supplied case-local evidence events."""
        requested = {self._event_index.get((case_id,e)) for e in event_ids}
        requested.discard(None)
        selected_edges = {e for e in self.edges if e.from_id in requested or e.to_id in requested}
        selected_nodes = requested | {e.from_id for e in selected_edges} | {e.to_id for e in selected_edges}
        return {
            'nodes':[asdict(self.nodes[n]) for n in sorted(selected_nodes)],
            'edges':[asdict(e) for e in sorted(selected_edges)],
            'event_ids':sorted(event_ids),
            'case_id':case_id,
        }

    def snapshot(self) -> dict:
        content = {'nodes':[asdict(n) for n in sorted(self.nodes.values())],
                   'edges':[asdict(e) for e in sorted(self.edges)]}
        body=json.dumps(content,sort_keys=True,separators=(',',':'))
        return {'graph':content,'sha256':hashlib.sha256(body.encode()).hexdigest(),
                'notes':'graph hash is a checksum, not a signed attestation'}
