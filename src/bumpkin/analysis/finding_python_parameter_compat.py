import ast
from dataclasses import dataclass

from bumpkin.analysis.finding_python_surface_base import split_top_level_params


@dataclass(frozen=True)
class PythonParameterSpec:
    name: str
    kind: str
    required: bool
    annotation: str | None


def is_optional_param(token: str) -> bool:
    value = token.strip()
    if not value:
        return False
    if value.startswith("..."):
        return True
    if "=" in value:
        return True
    left = value.split(":", 1)[0]
    return left.endswith("?")


def normalize_python_annotation(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    return ast.unparse(node).strip()


def parse_python_parameter_specs(params: str) -> list[PythonParameterSpec] | None:
    try:
        module = ast.parse(f"def _bumpkin_probe({params}):\n    pass\n")
    except SyntaxError:
        return None
    if len(module.body) != 1 or not isinstance(module.body[0], ast.FunctionDef):
        return None

    arguments = module.body[0].args
    specs: list[PythonParameterSpec] = []
    positional_args = [*arguments.posonlyargs, *arguments.args]
    positional_defaults: list[ast.expr | None] = [None] * (
        len(positional_args) - len(arguments.defaults)
    ) + list(arguments.defaults)

    for index, argument in enumerate(arguments.posonlyargs):
        specs.append(
            PythonParameterSpec(
                name=argument.arg,
                kind="posonly",
                required=positional_defaults[index] is None,
                annotation=normalize_python_annotation(argument.annotation),
            )
        )

    positional_offset = len(arguments.posonlyargs)
    for offset, argument in enumerate(arguments.args):
        specs.append(
            PythonParameterSpec(
                name=argument.arg,
                kind="arg",
                required=positional_defaults[positional_offset + offset] is None,
                annotation=normalize_python_annotation(argument.annotation),
            )
        )

    if arguments.vararg is not None:
        specs.append(
            PythonParameterSpec(
                name=arguments.vararg.arg,
                kind="vararg",
                required=False,
                annotation=normalize_python_annotation(arguments.vararg.annotation),
            )
        )

    for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=False):
        specs.append(
            PythonParameterSpec(
                name=argument.arg,
                kind="kwonly",
                required=default is None,
                annotation=normalize_python_annotation(argument.annotation),
            )
        )

    if arguments.kwarg is not None:
        specs.append(
            PythonParameterSpec(
                name=arguments.kwarg.arg,
                kind="varkw",
                required=False,
                annotation=normalize_python_annotation(arguments.kwarg.annotation),
            )
        )

    return specs


def is_python_parameter_name_compatible(
    old_param: PythonParameterSpec,
    new_param: PythonParameterSpec,
) -> bool:
    if old_param.kind in {"posonly", "vararg", "varkw"}:
        return True
    return old_param.name == new_param.name


def is_python_parameter_kind_compatible(
    old_param: PythonParameterSpec,
    new_param: PythonParameterSpec,
) -> bool:
    if old_param.kind == new_param.kind:
        return True
    return new_param.kind == "arg" and old_param.kind in {"kwonly", "posonly"}


def same_python_parameter_surface(
    old_param: PythonParameterSpec,
    new_param: PythonParameterSpec,
) -> bool:
    return (
        is_python_parameter_name_compatible(old_param, new_param)
        and old_param.kind == new_param.kind
        and old_param.required == new_param.required
        and old_param.annotation == new_param.annotation
    )


def is_python_parameter_surface_compatible(
    old_param: PythonParameterSpec,
    new_param: PythonParameterSpec,
) -> bool:
    return (
        is_python_parameter_name_compatible(old_param, new_param)
        and is_python_parameter_kind_compatible(old_param, new_param)
        and old_param.required == new_param.required
        and old_param.annotation == new_param.annotation
    )


def has_compatible_python_parameter_surface(old_params: str, new_params: str) -> bool:
    old_specs = parse_python_parameter_specs(old_params)
    new_specs = parse_python_parameter_specs(new_params)
    if old_specs is None or new_specs is None or len(old_specs) != len(new_specs):
        return False
    return all(
        is_python_parameter_surface_compatible(old_spec, new_spec)
        for old_spec, new_spec in zip(old_specs, new_specs, strict=False)
    )


def is_optional_widening(old_params: str, new_params: str) -> bool:
    old_specs = parse_python_parameter_specs(old_params)
    new_specs = parse_python_parameter_specs(new_params)
    if old_specs is not None and new_specs is not None:
        if len(new_specs) < len(old_specs):
            return False
        if len(new_specs) == len(old_specs):
            widened_existing = False
            for old_spec, new_spec in zip(old_specs, new_specs, strict=False):
                if not (
                    is_python_parameter_name_compatible(old_spec, new_spec)
                    and is_python_parameter_kind_compatible(old_spec, new_spec)
                    and old_spec.annotation == new_spec.annotation
                ):
                    return False
                if old_spec.required and not new_spec.required:
                    widened_existing = True
                elif old_spec.required != new_spec.required:
                    return False
            return widened_existing
        if not all(
            same_python_parameter_surface(old_spec, new_spec)
            for old_spec, new_spec in zip(old_specs, new_specs[: len(old_specs)], strict=False)
        ):
            return False
        extras = new_specs[len(old_specs) :]
        return bool(extras) and all(not extra.required for extra in extras)

    old_list = split_top_level_params(old_params)
    new_list = split_top_level_params(new_params)
    if len(new_list) < len(old_list):
        return False
    if new_list[: len(old_list)] != old_list:
        return False
    extras = new_list[len(old_list) :]
    if not extras:
        return False
    return all(is_optional_param(param) for param in extras)


def is_requiredness_tightening(old_params: str, new_params: str) -> bool:
    old_specs = parse_python_parameter_specs(old_params)
    new_specs = parse_python_parameter_specs(new_params)
    if old_specs is not None and new_specs is not None:
        if len(new_specs) < len(old_specs):
            return True

        for index, old_spec in enumerate(old_specs):
            if index >= len(new_specs):
                return True
            new_spec = new_specs[index]
            if not is_python_parameter_name_compatible(
                old_spec, new_spec
            ) or not is_python_parameter_kind_compatible(old_spec, new_spec):
                return False
            if not old_spec.required and new_spec.required:
                return True

        extras = new_specs[len(old_specs) :]
        return any(extra.required for extra in extras)

    old_list = split_top_level_params(old_params)
    new_list = split_top_level_params(new_params)
    if len(new_list) < len(old_list):
        return True

    for index, old_token in enumerate(old_list):
        if index >= len(new_list):
            return True
        new_token = new_list[index]
        if old_token == new_token:
            continue
        if is_optional_param(old_token) and not is_optional_param(new_token):
            return True
        return True

    if len(new_list) > len(old_list):
        extras = new_list[len(old_list) :]
        return not all(is_optional_param(param) for param in extras)

    return False
