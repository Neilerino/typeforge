from datetime import datetime
from typing import assert_type

from api import (
    JsonSafe_Post,
    JsonSafe_User,
    Post,
    User,
    collect,
    jsonify,
    read,
    serialize,
)

assert_type(collect(1, "two"), tuple[int, str])
assert_type(read("text"), str)
assert_type(serialize(1), float)

post: Post = {"title": "Hello World"}

result = jsonify(post)
assert_type(result, JsonSafe_Post)

user: User = {"name": "Ada", "created_at": datetime.now()}
assert_type(jsonify(user), JsonSafe_User)
