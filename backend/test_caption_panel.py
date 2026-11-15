import math
import unittest
from reaction_render import fit_caption_panel

class CaptionPanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_fitting_chunks_share_page_without_losing_timing_or_text(self):
        async def measure(text):return math.ceil(len(text)/10)
        chunks=[{'start':i,'end':i+1,'text':'字'*12} for i in range(4)]
        pages=await fit_caption_panel(chunks,measure)
        self.assertEqual(len(pages),2)
        self.assertEqual(pages[0]['start'],0);self.assertEqual(pages[0]['end'],3)
        self.assertEqual(pages[1]['start'],3);self.assertEqual(pages[1]['end'],4)
        self.assertEqual(''.join(p['text'] for p in pages),'字'*48)
        self.assertEqual(len(chunks),4)
    async def test_overflow_is_not_silently_clipped(self):
        async def measure(text):return 5
        with self.assertRaises(ValueError):
            await fit_caption_panel([{'start':0,'end':1,'text':'overflow'}],measure)
