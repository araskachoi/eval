"""Content-dropping parser for documented codex exec --json event shapes.

This does not launch Codex or read its private session files. Only a single
explicitly supplied event stream is accepted; subagent attribution is unknown.
"""
from .core import new_id


class CliEvents:
    def __init__(self, thread_id):
        self.thread_id=thread_id
        self.turn=None

    def feed(self, raw, occurred_at):
        kind=raw.get('type')
        def event(event_kind,**fields):
            return dict(event_id=new_id(),thread_id=self.thread_id,execution_id=self.turn,
                        occurred_at=occurred_at,kind=event_kind,**fields)
        if kind=='turn.started':
            if self.turn:
                raise ValueError('Overlapping turns are unsupported by the CLI adapter')
            self.turn=new_id()
            return [event('execution',parent_id=None,status='running')]
        if kind in {'turn.completed','turn.failed'}:
            if not self.turn:
                raise ValueError('Turn end without start')
            events=[]
            usage=raw.get('usage')
            if kind=='turn.completed' and isinstance(usage,dict):
                events.append(event('usage',scope='self',mode='cumulative',model=None,harness='codex',
                                    input=usage.get('input_tokens'),cached=usage.get('cached_input_tokens'),
                                    output=usage.get('output_tokens'),reasoning=None))
            events.append(event('execution',parent_id=None,status='completed' if kind=='turn.completed' else 'failed'))
            self.turn=None
            return events
        if kind=='item.completed' and self.turn:
            item=raw.get('item',{})
            tool={'command_execution':'shell','mcp_tool_call':'mcp','web_search':'browser','file_change':'file'}.get(item.get('type'))
            if tool:
                failed=item.get('status')=='failed' or (item.get('exit_code') is not None and item.get('exit_code')!=0)
                return [event('tool',tool=tool,status='failed' if failed else 'completed',duration_ms=None)]
        return []
