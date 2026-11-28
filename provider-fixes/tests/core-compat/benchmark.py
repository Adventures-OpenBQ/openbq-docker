from statistics import median
from time import perf_counter
import pandas as pd
from openbb_core.app.utils import df_to_basemodel
values=pd.DataFrame({'date':['2024-01-01']*10000, 'value':range(10000)})
times=[]
for _ in range(5):
    frame=values.copy(); start=perf_counter(); result=df_to_basemodel(frame); times.append(perf_counter()-start)
assert len(result)==10000 and result[0].model_dump()['date']=='2024-01-01'
print({'rows':10000,'runs':5,'median_seconds':median(times),'times':times})
