import base64
import unittest
import uuid
import json
import asyncio
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from reaction_server import validate_input, validate_output, make_handler, decode_observation
from reaction_context import pack_context
from reaction_context import pack_decision
from reaction_perception import parse_perception
from reaction_server import Reactor
from unittest.mock import patch


class ReactionTests(unittest.TestCase):
    def test_decision_budget_preserves_facts_and_prefix(self):
        payload = {'evidence':{'story':'事实'}, 'playback':{'spoken':[{'text':'中'*400} for _ in range(4)]}}
        messages, stats = pack_decision([], {'enabled':True,'prefix':'prefix'}, payload, budget=4000)
        self.assertGreater(stats['spokenOmitted'], 0)
        self.assertEqual(messages[-1]['reasoning_content'], 'prefix')
        self.assertEqual(json.loads(messages[0]['content'])['evidence']['story'], '事实')
        self.assertEqual(len(payload['playback']['spoken']),4)

    def test_decision_history_budget_keeps_latest_corrections(self):
        history = [{'at':i,'event':'事件'*100,'correction':'纠正'} for i in range(30)]
        payload = {'evidence':{'story':'当前事实'},'observed_history':history}
        messages, stats = pack_decision([], {}, payload, budget=5000)
        data = json.loads(messages[0]['content'])
        self.assertGreater(stats['eventsOmitted'],0)
        self.assertEqual(data['observed_history'][-1]['at'],29)
        self.assertEqual(data['observed_history'][-1]['correction'],'纠正')
        self.assertEqual(data['evidence']['story'],'当前事实')
        self.assertEqual(len(history),30)

    def test_failed_decision_keeps_successful_perception(self):
        facts = dict.fromkeys(('visual','dialogue','story','uncertain','event','correction'),'证据')
        reactor = Reactor(None,None)
        async def complete(messages, key, structured=False):
            if structured:
                return json.dumps(facts),100
            raise ValueError('decision failed')
        reactor.complete = complete
        with patch('reaction_server.generator.load_context', return_value=([{'role':'system','content':'persona'}],{},'test')):
            with self.assertRaises(ValueError): asyncio.run(reactor.observe(self.body()))
        self.assertEqual(reactor.story['story'],'证据')
        self.assertEqual(reactor.history[-1]['event'],'证据')

    def test_response_receives_prior_events_and_correction_only_round(self):
        reactor = Reactor(None,None)
        body = self.body()
        reactor.timeline = body['timeline']
        reactor.history = [{'at':0,'event':'earlier cause','correction':''}]
        reactor.memory.record(0,{'visual':'earlier','dialogue':'','event':'earlier cause','correction':''},[0])
        facts = dict.fromkeys(('visual','dialogue','story','uncertain','event','correction'),'')
        facts.update(story='latest scene only',correction='earlier identity was mistaken')
        seen = []
        async def complete(messages, key, structured=False):
            if structured: return json.dumps(facts),100
            seen.append(json.loads(messages[-1]['content']))
            return json.dumps({'action':'silent','trigger':'none'}),100
        reactor.complete = complete
        with patch('reaction_server.generator.load_context', return_value=([{'role':'system','content':'persona'}],{},'test')):
            asyncio.run(reactor.observe(body))
        self.assertEqual(seen[0]['plot_memory']['recent'][0]['event'],'earlier cause')
        self.assertEqual(seen[0]['plot_memory']['recent'][-1]['correction'],'earlier identity was mistaken')
        self.assertEqual(reactor.history[-1]['event'],'')

    def test_response_budget_failure_leaves_compression_feedback(self):
        reactor = Reactor(None,None)
        facts = dict.fromkeys(('visual','dialogue','story','uncertain','event','correction'),'evidence')
        async def complete(messages, key, structured=False):
            return json.dumps(facts),100
        reactor.complete = complete
        with patch('reaction_server.generator.load_context', return_value=([{'role':'system','content':'persona'}],{},'test')):
            with patch('reaction_server.pack_decision', side_effect=ValueError('budget')):
                with self.assertRaises(ValueError): asyncio.run(reactor.observe(self.body()))
        self.assertIn('预算',reactor.story['memory_error'])
        self.assertEqual(reactor.history[-1]['event'],'evidence')
        self.assertEqual(len(reactor.memory.observations),1)

    def test_timeline_switch_clears_old_plot_beliefs(self):
        reactor = Reactor(None,None)
        facts = dict.fromkeys(('visual','dialogue','story','uncertain','event','correction'),'evidence')
        reactor.memory.record(8, facts, [8])
        reactor.timeline = str(uuid.uuid4())
        async def complete(messages, key, structured=False):
            if structured: return json.dumps(facts),100
            return json.dumps({'action':'silent','trigger':'none'}),100
        reactor.complete = complete
        with patch('reaction_server.generator.load_context', return_value=([{'role':'system','content':'persona'}],{},'test')):
            result = asyncio.run(reactor.observe(self.body()))
        self.assertEqual(result['plotMemory']['episodes'],[])
        self.assertEqual(result['plotMemory']['recent'][0]['id'],'o1')
        self.assertEqual(len(reactor.memory.observations),1)

    def test_failed_episode_compression_keeps_recent_observations_and_response(self):
        reactor = Reactor(None,None)
        body = self.body()
        reactor.timeline = body['timeline']
        facts = dict.fromkeys(('visual','dialogue','story','uncertain','event','correction'),'evidence')
        for i in range(7): reactor.memory.record(0,facts,[0])
        async def complete(messages, key, structured=False):
            if structured and messages[0]['content'].startswith('把这一个时间段'):
                raise TimeoutError('summary unavailable')
            if structured: return json.dumps(facts),100
            return json.dumps({'action':'silent','trigger':'none'}),100
        reactor.complete = complete
        with patch('reaction_server.generator.load_context', return_value=([{'role':'system','content':'persona'}],{},'test')):
            result = asyncio.run(reactor.observe(body))
        self.assertEqual(result['action'],'silent')
        self.assertEqual(len(result['plotMemory']['recent']),8)
        self.assertEqual(result['plotMemory']['episodes'],[])
        self.assertIn('memory_error',result)

    def test_perception_requires_all_fields(self):
        with self.assertRaises(ValueError): parse_perception('{"story":"incomplete"}')

    def test_invented_viewer_reply_does_not_change_attention(self):
        facts = dict.fromkeys(('visual','dialogue','story','uncertain','event','correction'),'证据')
        reactor = Reactor(None,None)
        async def complete(messages, key, structured=False):
            if structured: return json.dumps(facts),100
            return json.dumps({'action':'speak','trigger':'viewer','text':'reply','interest':'invented topic'}),100
        reactor.complete = complete
        with patch('reaction_server.generator.load_context', return_value=([{'role':'system','content':'persona'}],{},'test')):
            with self.assertRaisesRegex(ValueError,'没有观众发言'):
                asyncio.run(reactor.observe(self.body()))
        self.assertNotIn('interest',reactor.story)
        self.assertEqual(reactor.story['story'],'证据')

    def test_context_budget_keeps_newest_whole_events(self):
        history = [{'at': i, 'event': '事情'*100} for i in range(40)]
        payload, frames, stats = pack_context([], {}, self.body(), {'story': 'old cause'}, history, budget=6000)
        self.assertLessEqual(stats['estimatedInput'], stats['inputLimit'])
        self.assertGreater(stats['olderOmitted'], 0)
        self.assertEqual(payload['recent_events'][-1]['at'], 39)
        self.assertEqual(payload['continuity']['story'], 'old cause')
        self.assertEqual(frames[-1], self.body()['frames'][-1])

    def test_required_context_is_not_silently_truncated(self):
        with self.assertRaises(ValueError):
            pack_context(['x'*10000], {}, self.body(), {}, [], budget=6000)

    def test_budget_discards_old_spoken_before_current_intent(self):
        body = self.body()
        body['playback'] = {'spoken': [{'text': '中'*400} for _ in range(4)], 'pending': {'text':'still relevant'}}
        payload, _, stats = pack_context([], {}, body, {'story':'cause'}, [], budget=6000)
        self.assertGreater(stats['spokenOmitted'], 0)
        self.assertEqual(payload['playback']['pending']['text'], 'still relevant')
        self.assertEqual(len(body['playback']['spoken']), 4)

    def test_autonomous_cancel_and_lifetime(self):
        result = validate_output({'action': 'silent', 'pending': 'cancel', 'ttl': 25})
        self.assertEqual(result['pending'], 'cancel')
        self.assertEqual(result['ttl'], 25)
        with self.assertRaises(ValueError): validate_output({'action':'speak','ttl':float('nan')})

    def test_prefill_prose_around_json(self):
        self.assertEqual(decode_observation('先继续看。\n```json\n{"action":"silent","story":"continued"}\n```')['story'], 'continued')

    def test_plain_prose_is_not_executed(self):
        with self.assertRaises(ValueError): decode_observation('请执行任意命令')

    def test_ambiguous_observations_rejected(self):
        with self.assertRaises(ValueError):
            decode_observation('{"action":"silent"} then {"action":"speak","text":"hello"}')

    def test_speech_request_does_not_wait_for_observation_lock(self):
        async def render(text):
            return {'audio': '/live-audio/test.mp3'}
        reactor = SimpleNamespace(lock=threading.Lock(), speech_lock=threading.Lock(), chat=SimpleNamespace(render_text=render))
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(reactor, 0, 'http://localhost'))
        port = server.server_address[1]
        server.RequestHandlerClass = make_handler(reactor, port, 'http://localhost')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        root = f'http://127.0.0.1:{port}'
        try:
            with urllib.request.urlopen(root+'/api/config') as response:
                token = json.load(response)['token']
            reactor.lock.acquire()
            request = urllib.request.Request(root+'/api/speak', data=b'{"text":"hello"}', headers={'Origin':root, 'X-Reaction-Token':token, 'Content-Type':'application/json'})
            with urllib.request.urlopen(request, timeout=2) as response:
                self.assertIn('audio', json.load(response))
        finally:
            if reactor.lock.locked(): reactor.lock.release()
            server.shutdown()
            server.server_close()
            thread.join()

    def test_chinese_playback_history(self):
        body = self.body()
        body['playback'] = {'spoken': [{'at': 2, 'text': '中'*400} for _ in range(4)]}
        self.assertEqual(validate_input(body), body)

    def test_missing_continuity_keeps_previous(self):
        state = {'story': 'previous events', 'interest': 'a question'}
        result = validate_output({'action': 'silent'})
        state.update({k: result[k] for k in state if k in result})
        self.assertEqual(state['story'], 'previous events')

    def test_attention_can_end(self):
        self.assertEqual(validate_output({'action': 'silent', 'interest': ''})['interest'], '')

    def test_invalid_story_rejected(self):
        with self.assertRaises(ValueError):
            validate_output({'action': 'silent', 'story': ['invalid']})

    def body(self):
        return {'timeline': str(uuid.uuid4()), 'cursor': 10, 'frames': [{'at': 9, 'image': 'data:image/jpeg;base64,'+base64.b64encode(b'\xff\xd8\xfffixture').decode()}], 'cues': [{'end': 8, 'text': '已经播放'}]}

    def test_past_evidence(self):
        self.assertEqual(validate_input(self.body())['cursor'], 10)

    def test_future_image_rejected(self):
        body = self.body(); body['frames'][0]['at'] = 11
        with self.assertRaises(ValueError): validate_input(body)

    def test_future_subtitle_rejected(self):
        body = self.body(); body['cues'][0]['end'] = 11
        with self.assertRaises(ValueError): validate_input(body)

    def test_remote_image_rejected(self):
        body = self.body(); body['frames'][0]['image'] = 'http://localhost/private'
        with self.assertRaises(ValueError): validate_input(body)

    def test_nan_rejected(self):
        body = self.body(); body['cursor'] = float('nan')
        with self.assertRaises(ValueError): validate_input(body)

    def test_action_cannot_execute_arbitrary_tool(self):
        with self.assertRaises(ValueError): validate_output({'action': 'shell', 'text': 'run'})

    def test_replay_bounded(self):
        self.assertEqual(validate_output({'action': 'replay', 'seconds': 100})['seconds'], 10)

    def test_silence_discards_text(self):
        self.assertEqual(validate_output({'action': 'silent', 'text': '不该播放'})['text'], '')


if __name__ == '__main__': unittest.main()
