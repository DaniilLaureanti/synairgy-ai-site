import sys,unittest
from pathlib import Path
SRC=Path(__file__).resolve().parents[1]/"src"; sys.path.insert(0,str(SRC))
from ai_analyzer import normalize_score

class ScoreTests(unittest.TestCase):
    def test_score_is_sum_when_evidence_is_strong(self):
        result={"score_components":{"business_quality":18,"pain_strength":24,"synairgy_fit":22,"contactability":12,"evidence_confidence":9},"evidence":["Public fact"]}
        self.assertEqual(normalize_score(result,{"business_status":"OPERATIONAL","website":"https://example.com"},{"reachable":True}),85)
    def test_low_evidence_caps_score(self):
        result={"score_components":{"business_quality":20,"pain_strength":30,"synairgy_fit":25,"contactability":15,"evidence_confidence":3},"evidence":["Weak signal"]}
        self.assertEqual(normalize_score(result,{"business_status":"OPERATIONAL","website":"https://example.com"},{"reachable":True}),69)
    def test_non_operational_is_zero(self):
        result={"score_components":{"business_quality":20,"pain_strength":30,"synairgy_fit":25,"contactability":15,"evidence_confidence":10},"evidence":["Fact"]}
        self.assertEqual(normalize_score(result,{"business_status":"CLOSED_PERMANENTLY","website":""},{"reachable":False}),0)

if __name__=="__main__": unittest.main()
