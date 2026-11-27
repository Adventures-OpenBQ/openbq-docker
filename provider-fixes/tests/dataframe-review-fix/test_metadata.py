import unittest
import pandas as pd
from openbb_core.app.utils import df_to_basemodel,basemodel_to_df
from openbb_core.provider.abstract.data import Data
class Metadata(unittest.TestCase):
    def test_collision_roundtrip(self):
        reserved=['is_multiindex','multiindex_names','multiindex_columns','multiindex_data_columns']
        for columns in [[x] for x in reserved]+[reserved+[f'_{x}' for x in reserved]+['__is_multiindex']]:
            for names in [[None,None],['x','y'],['is_multiindex','multiindex_columns']]:
                with self.subTest(columns=columns,names=names):
                    frame=pd.DataFrame([['client_value']*len(columns),['other']*len(columns)],columns=columns,index=pd.MultiIndex.from_tuples([('a',1),('b',2)],names=names))
                    before=frame.copy(deep=True)
                    pd.testing.assert_frame_equal(basemodel_to_df(df_to_basemodel(frame)),before)
                    pd.testing.assert_frame_equal(frame,before)
    def test_date_missing_and_mixed_numeric(self):
        values=['2026-10-20T00:00:00-04:00','2026-11-19T00:00:00-05:00',None]
        records=df_to_basemodel(pd.DataFrame({'date':values}))
        self.assertEqual([r.model_dump().get('date') for r in records],['2026-10-20','2026-11-19',None])
    def test_reverse_date_missing(self):
        values=['2026-10-20T00:00:00-04:00','2026-11-19T00:00:00-05:00',None]
        restored=basemodel_to_df([Data(date=v) for v in values])
        self.assertEqual([str(v) for v in restored['date'][:2]],['2026-10-20','2026-11-19'])
        self.assertTrue(pd.isna(restored['date'].iloc[2]))
    def test_mixed_numeric_date(self):
        mixed=['2026-10-20',123]
        self.assertEqual([r.model_dump()['date'] for r in df_to_basemodel(pd.DataFrame({'date':mixed}))],mixed)
        self.assertEqual(basemodel_to_df([Data(date=v) for v in mixed])['date'].tolist(),mixed)

    def test_legacy_records(self):
        data=[Data(x='a',y=1,value=5,is_multiindex=True,multiindex_names="['x', 'y']")]
        expected=pd.DataFrame({'value':[5]},index=pd.MultiIndex.from_tuples([('a',1)],names=['x','y']))
        pd.testing.assert_frame_equal(basemodel_to_df(data),expected)
    def test_legacy_collision_level_records(self):
        data=[Data(_x='a',y=1,x=5,is_multiindex=True,multiindex_names="['x', 'y']",multiindex_columns="['_x', 'y']")]
        expected=pd.DataFrame({'x':[5]},index=pd.MultiIndex.from_tuples([('a',1)],names=['x','y']))
        pd.testing.assert_frame_equal(basemodel_to_df(data),expected)
    def test_plain_reserved_columns(self):
        frame=pd.DataFrame({'is_multiindex':['client_value'],'multiindex_names':['client_value'],'multiindex_columns':['client_value']})
        pd.testing.assert_frame_equal(basemodel_to_df(df_to_basemodel(frame)),frame)
if __name__=='__main__':unittest.main(verbosity=2)
