"""Deterministic fixture failure-path probe; original failure must stay visible."""
import argparse,json,sys,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path.cwd()/'scripts'))
import check_python
check_python.configure_imports()
import test_personal_orx_projects as cases
parser=argparse.ArgumentParser();parser.add_argument('--expect-release',choices=['true','false'],required=True);args=parser.parse_args()
events=[]
class Event:
 def __init__(self): self.event=threading.Event();self.index=len(events);events.append(self);self.wait_result=None
 def set(self): return self.event.set()
 def wait(self,timeout=None):
  self.wait_result=self.event.wait(timeout)
  return False if self.index==0 else self.wait_result
case=cases.ProjectTests('test_double_click_concurrent_reservation_dispatches_once')
started=time.monotonic();result=unittest.TestResult()
with patch.object(cases,'threading',SimpleNamespace(Event=Event)):
 case.run(result)
report={'expectedAssertionFailure':len(result.failures)==1 and not result.errors,'originalEnteredActuallySet':events[0].event.is_set(),'releaseSet':events[1].event.is_set(),'workerReleaseWaitResult':events[1].wait_result,'seconds':time.monotonic()-started,'testFailures':len(result.failures),'testErrors':len(result.errors)}
print(json.dumps(report))
for _,trace in result.failures: print(trace)
assert report['expectedAssertionFailure'] and report['originalEnteredActuallySet']
assert report['releaseSet']==(args.expect_release=='true')
