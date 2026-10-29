import unittest
from codex_eval.cli_events import CliEvents
from codex_eval.core import new_id, normalize


class CliEventTests(unittest.TestCase):
    def test_usage_and_tool_output_content_are_separated(self):
        parser=CliEvents(new_id())
        normalized=[]
        for raw in [
            {'type':'turn.started'},
            {'type':'item.completed','item':{'type':'command_execution','command':'not executed','aggregated_output':'SYNTHETICKEY','exit_code':1}},
            {'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':20,'output_tokens':30}},
        ]:
            normalized.extend(normalize(e) for e in parser.feed(raw,1))
        self.assertEqual(normalized[1]['tool'],'shell')
        self.assertEqual(normalized[1]['status'],'failed')
        self.assertEqual(normalized[2]['input'],100)
        self.assertEqual(normalized[2]['harness'],'codex')
        self.assertIsNone(normalized[2]['model'])
        self.assertNotIn('SYNTHETICKEY',str(normalized))
        self.assertNotIn('not executed',str(normalized))

    def test_missing_usage_stays_missing(self):
        parser=CliEvents(new_id())
        parser.feed({'type':'turn.started'},1)
        self.assertEqual(len(parser.feed({'type':'turn.completed'},2)),1)

    def test_ambiguous_boundaries_rejected(self):
        parser=CliEvents(new_id())
        with self.assertRaises(ValueError): parser.feed({'type':'turn.completed'},1)
        parser.feed({'type':'turn.started'},1)
        with self.assertRaises(ValueError): parser.feed({'type':'turn.started'},1)
