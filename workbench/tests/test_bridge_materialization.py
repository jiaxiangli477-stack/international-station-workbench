import unittest
from bridge_materialization import account_scoped_messages


class AccountScopedMessageTests(unittest.TestCase):
    def test_duplicate_conversation_ids_refetch_per_seller(self):
        conversations=[
            {'conversationId':'same','sellerAliId':'seller-1','contactAliId':'buyer-1'},
            {'conversationId':'same','sellerAliId':'seller-2','contactAliId':'buyer-2'},
            {'conversationId':'unique','sellerAliId':'seller-1','contactAliId':'buyer-3'},
        ]
        bulk=[
            {'conversationId':'same','messages':[{'text':'ambiguous-1'}]},
            {'conversationId':'same','messages':[{'text':'ambiguous-2'}]},
            {'conversationId':'unique','messages':[{'text':'bulk'}]},
        ]
        calls=[]
        def fetch(conversation):
            calls.append(conversation['sellerAliId'])
            return [{'text':conversation['sellerAliId']}]
        result=account_scoped_messages(conversations,bulk,fetch)
        self.assertEqual(calls,['seller-1','seller-2'])
        self.assertEqual(result[('seller-1','same')],[{'text':'seller-1'}])
        self.assertEqual(result[('seller-2','same')],[{'text':'seller-2'}])
        self.assertEqual(result[('seller-1','unique')],[{'text':'bulk'}])

    def test_duplicate_id_inside_one_seller_fails_closed(self):
        conversations=[
            {'conversationId':'same','sellerAliId':'seller-1'},
            {'conversationId':'same','sellerAliId':'seller-1'},
        ]
        bulk=[{'conversationId':'same','messages':[]},{'conversationId':'same','messages':[]}]
        with self.assertRaises(ValueError):
            account_scoped_messages(conversations,bulk,lambda _: [])

    def test_collision_can_recover_one_truly_empty_account(self):
        conversations=[{'conversationId':'same','sellerAliId':'seller-1'},
                       {'conversationId':'same','sellerAliId':'seller-2'}]
        bulk=[{'conversationId':'same','messages':[{'text':'question'}]}]
        result=account_scoped_messages(conversations,bulk,
            lambda row:[] if row['sellerAliId']=='seller-1' else [{'text':'question'}])
        self.assertEqual(result[('seller-1','same')],[])
        self.assertEqual(result[('seller-2','same')],[{'text':'question'}])

    def test_unknown_conversation_or_wrong_explicit_account_is_rejected(self):
        conversation=[{'conversationId':'known','sellerAliId':'seller-1'}]
        for rows in ([{'conversationId':'unknown','messages':[]}],
                     [{'conversationId':'known','sellerAliId':'seller-2','messages':[]}]):
            with self.assertRaises(ValueError):account_scoped_messages(conversation,rows,lambda _:[])


if __name__=='__main__':
    unittest.main()
