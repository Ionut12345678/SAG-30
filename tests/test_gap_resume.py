import unittest
from radar.gap_resume import preflight, INCIDENT_RUN, PUBLISHED_RUN, PUBLISHED_DB_SHA

def fixtures():
    health={'checkpoint':{'workflow_run_id':PUBLISHED_RUN,'database_sha256':PUBLISHED_DB_SHA}}
    manifest={'workflow_run_id':PUBLISHED_RUN,'database_sha256':PUBLISHED_DB_SHA,
              'audit_retention':'ALL_ROWS_NO_PRUNING'}
    artifacts=[{'name':'sag30-restart-diagnostic','id':11827202525}]
    return health,manifest,artifacts

class GapResumeTests(unittest.TestCase):
    def test_explicit_approval_prepares_only_and_preserves_gap(self):
        result=preflight(*fixtures(),operator_authorized=True)
        self.assertEqual(result['preflight'],'PASS_PREPARATION_ONLY')
        self.assertEqual(result['incident_workflow_run_id'],INCIDENT_RUN)
        self.assertEqual(result['incident_status'],'UNKNOWN_NOT_RECOVERED')
        self.assertEqual(result['gate0'],'BLOCKED')
        self.assertTrue(result['data_gap'])
        self.assertFalse(result['first_seen_reconstruction'])
        self.assertFalse(result['resume_executed'])
        self.assertFalse(result['buy'])

    def test_approval_missing_blocks(self):
        result=preflight(*fixtures())
        self.assertEqual(result['preflight'],'BLOCKED')
        self.assertIn('OPERATOR_AUTHORIZATION_MISSING',result['errors'])

    def test_parent_hash_or_run_change_blocks(self):
        for side,key,value in [(0,'database_sha256','0'*64),
                               (1,'workflow_run_id','unexpected'),
                               (1,'audit_retention','PRUNED')]:
            inputs=list(fixtures())
            if side==0: inputs[0]['checkpoint'][key]=value
            else: inputs[1][key]=value
            result=preflight(*inputs,operator_authorized=True)
            self.assertEqual(result['preflight'],'BLOCKED')

    def test_new_recovery_artifact_forces_exact_recovery_instead_of_gap_resume(self):
        health,manifest,artifacts=fixtures()
        artifacts.append({'name':'sag30-checkpoint-recovery'})
        result=preflight(health,manifest,artifacts,operator_authorized=True)
        self.assertIn('RECOVERY_ARTIFACT_EXISTS_USE_EXACT_RECOVERY',result['errors'])

    def test_no_inventory_or_diagnostic_fails_closed(self):
        health,manifest,_=fixtures()
        for inventory in (None,[],[{'name':'irrelevant'}]):
            result=preflight(health,manifest,inventory,operator_authorized=True)
            self.assertEqual(result['preflight'],'BLOCKED')
