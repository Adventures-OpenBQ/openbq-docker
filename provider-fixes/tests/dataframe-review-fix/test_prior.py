import unittest
from inspect import Parameter
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
from pydantic import Field, BaseModel
from typing import Annotated
from openbb_core.app.utils import df_to_basemodel, basemodel_to_df
from openbb_core.app.static.package_builder.method_definition import MethodDefinition
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.helpers import combine_certificates
from openbb_imf.models.port_volume import ImfPortVolumeQueryParams

class Compatibility(unittest.TestCase):
    def test_default_factory_signature(self):
        class Params(QueryParams):
            symbol: str
            models: list[str] = Field(default_factory=lambda: ['std'])
        out = MethodDefinition.format_params('/x/y', {'params': Parameter('params', Parameter.POSITIONAL_OR_KEYWORD, annotation=Params)})
        self.assertIs(out['symbol'].default, Parameter.empty)
        self.assertEqual(out['models'].default, ['std'])

    def test_annotated_factory_signature(self):
        class Model(BaseModel):
            symbol: str
            columns: list[str] = Field(default_factory=lambda: ['close'])
        with patch.object(MethodDefinition, 'is_data_processing_function', return_value=False):
            out=MethodDefinition.format_params('/x/y', {'params': Parameter('params', Parameter.POSITIONAL_OR_KEYWORD, annotation=Annotated[Model, 'meta'])})
        self.assertEqual(out['columns'].default, ['close'])
        self.assertIs(out['symbol'].default, Parameter.empty)

    def test_date_fallback(self):
        real=pd.to_datetime
        def parse(arg,*args,**kwargs):
            if isinstance(arg,pd.Series): raise ValueError('mixed timezone')
            return real(arg,*args,**kwargs)
        with patch.object(pd,'to_datetime',parse):
            out=df_to_basemodel(pd.DataFrame({'date':['2024-01-01','2024-01-02']}))
        self.assertEqual([d.model_dump()['date'] for d in out],['2024-01-01','2024-01-02'])

    def test_multiindex_roundtrip(self):
        for names, cols in [([None,None],['v']), (['x',None],['v']), (['x','x'],['v']), ([None,'y'],['level_0'])]:
            with self.subTest(names=names):
                frame=pd.DataFrame([1,2],columns=cols,index=pd.MultiIndex.from_tuples([('a',1),('b',2)],names=names))
                before=frame.copy(deep=True)
                pd.testing.assert_frame_equal(basemodel_to_df(df_to_basemodel(frame)),before)
                pd.testing.assert_frame_equal(frame,before)

    def test_date_numeric_and_invalid(self):
        for values in [[1,2],['foo','bar']]:
            self.assertEqual([d.model_dump()['date'] for d in df_to_basemodel(pd.DataFrame({'date': values}))],values)

    def test_date_vectorized(self):
        real=pd.to_datetime
        calls=[]
        def tracked(arg,*args,**kwargs):
            calls.append(type(arg))
            return real(arg,*args,**kwargs)
        with patch.object(pd,'to_datetime',tracked):
            out=df_to_basemodel(pd.DataFrame({'date':['2024-01-01']*1000}))
        self.assertEqual(out[0].model_dump()['date'],'2024-01-01')
        self.assertEqual(calls,[pd.Series])

    def test_date_mixed_offsets(self):
        out=df_to_basemodel(pd.DataFrame({'date':['2023-11-03 00:00:00-04:00','2023-11-06 00:00:00-05:00']}))
        self.assertEqual([d.model_dump()['date'] for d in out],['2023-11-03','2023-11-06'])

    def test_ca_paths(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/'.certs';root.mkdir()
            bundle=Path(tmp)/'bundle.pem';bundle.write_text('BUNDLE')
            for name in ['ca.pem','ca','ca.company.pem']:
                with self.subTest(name=name):
                    cert=root/name;cert.write_text('CERT')
                    expected=cert.with_name(cert.stem+'_combined'+cert.suffix)
                    result=Path(combine_certificates(str(cert),str(bundle)))
                    self.assertEqual(result,expected)
                    self.assertEqual(result.read_text(),'BUNDLECERT')
                    self.assertEqual(combine_certificates(str(result)),str(result))

    def test_imf_snake_names(self):
        choices=[{'label':'Rotterdam','value':'port1114'},{'label':'Singapore','value':'port1201'}]
        with patch('openbb_imf.models.port_volume.get_port_id_choices',return_value=choices):
            self.assertEqual(ImfPortVolumeQueryParams(port_code='rotterdam,singapore').port_code,'port1114,port1201')

if __name__=='__main__': unittest.main(verbosity=2)
