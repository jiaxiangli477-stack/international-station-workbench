import unittest
import attribute_plan
import single_approval_flow as single


class RecruitmentDraftPolicyTests(unittest.TestCase):
    def product(self):
        proposal={'revision':1,'manifest':{'fields':{'product_name':'Protein Powder'}},
                  'field_sources':{'fields.product_name':{'kind':'DESIGN','source':'adopted product concept'}},
                  'unresolved':['dosage_form_conflict: theme Gummy, product Powder','m7_dependency: old stage','net_weight: missing']}
        proposal['fingerprint']=attribute_plan.fingerprint(proposal)
        return {'revision':1,'recruitment':{'id':'theme'},'workflow':{'approvalPolicy':single.POLICY},'attributePlan':proposal}

    def test_visual_reference_policy_does_not_turn_theme_mismatch_into_draft_fact_failure(self):
        p=self.product();old=p['attributePlan']['fingerprint']
        self.assertEqual(single.fact_gaps(p),['net_weight: missing'])
        self.assertEqual(p['attributePlan']['fingerprint'],old)
        self.assertEqual(len(p['attributePlan']['unresolved']),3)

    def test_strict_theme_policy_retains_all_conflicts(self):
        p=self.product();p['workflow']['recruitmentMatchPolicy']='strict'
        self.assertEqual(single.fact_gaps(p),p['attributePlan']['unresolved'])


if __name__=='__main__':unittest.main()
