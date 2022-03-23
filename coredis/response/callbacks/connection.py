from typing import Any, AnyStr, Dict, List, Set, Union

from frozendict import frozendict

from coredis.response.callbacks import SimpleCallback
from coredis.utils import pairs_to_dict


class ClientTrackingInfoCallback(SimpleCallback):
    def transform_3(
        self, response: Any
    ) -> Dict[AnyStr, Union[AnyStr, Set[AnyStr], List[AnyStr]]]:
        if isinstance(response, frozendict):
            return dict(response)
        return response

    def transform(
        self, response: Any
    ) -> Dict[AnyStr, Union[AnyStr, Set[AnyStr], List[AnyStr]]]:
        response = dict(pairs_to_dict(response))
        response["flags"] = set(response["flags"])
        return response