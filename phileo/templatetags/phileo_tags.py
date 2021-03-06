from django import template

from django.template.loader import render_to_string
from django.contrib.contenttypes.models import ContentType

from phileo.models import Like
from phileo.utils import _allowed, widget_context
from phileo.settings import LIKABLE_MODELS

register = template.Library()


@register.assignment_tag
def who_likes(obj):
    return Like.objects.filter(
        receiver_content_type=ContentType.objects.get_for_model(obj),
        receiver_object_id=obj.pk
    )


@register.assignment_tag
def likes(user, *models):
    content_types = []
    model_list = models or LIKABLE_MODELS.keys()
    for model in model_list:
        if not _allowed(model):
            continue
        app, model = model.split(".")
        content_types.append(
            ContentType.objects.get(app_label=app, model__iexact=model)
        )
    return Like.objects.filter(sender=user, receiver_content_type__in=content_types)


class LikeRenderer(template.Node):

    def __init__(self, varname):
        self.varname = template.Variable(varname)

    def render(self, context):
        like = self.varname.resolve(context)

        instance = like.receiver
        content_type = like.receiver_content_type
        app_name = content_type.app_label
        model_name = content_type.model.lower()

        like_context = {
            'instance': instance,
            'like': like,
        }

        return render_to_string([
            'phileo/{0}/{1}.html'.format(app_name, model_name),
            'phileo/{0}/like.html'.format(app_name),
            'phileo/_like.html',
        ], like_context, context)


@register.tag
def render_like(parser, token):
    """
    {% likes user as like_list %}
    <ul>
        {% for like in like_list %}
            <li>{% render_like like %}</li>
        {% endfor %}
    </ul>
    """

    tokens = token.split_contents()
    var = tokens[1]

    return LikeRenderer(var)


@register.filter
def likes_count(obj):
    """
    Something like:

        <div class="likes_count">{{ obj|likes_count }}</div>

    will render:

        <div class="likes_count">34</div>
    """
    return Like.objects.filter(
        receiver_content_type=ContentType.objects.get_for_model(obj),
        receiver_object_id=obj.pk
    ).count()


@register.inclusion_tag("phileo/_widget.html")
def phileo_widget(user, obj):
    return widget_context(user, obj)


@register.inclusion_tag("phileo/_widget_brief.html")
def phileo_widget_brief(user, obj):
    return widget_context(user, obj)


class ObjectDecorator(object):

    def __init__(self, user, objects):
        self.user = user
        self._objects = objects
        self._is_stream = None

    def is_stream(self):
        if self._is_stream is None and len(self._objects) > 0:
            self._is_stream = not hasattr(self._objects[0], "_meta")
        return self._is_stream

    def get_id(self, obj):
        return self.is_stream() and obj.item.id or obj.id

    @property
    def indexed(self):
        if not hasattr(self, "_indexed"):
            self._indexed = {}
            for obj in self._objects:
                if hasattr(obj, "cast") and callable(obj.cast):
                    obj = obj.cast()
                ct = ContentType.objects.get_for_model(self.is_stream() and obj.item or obj)
                if ct not in self._indexed.keys():
                    self._indexed[ct] = []
                obj.liked = False
                self._indexed[ct].append(obj)
        return self._indexed

    def objects(self):
        for ct in self.indexed.keys():
            likes = Like.objects.filter(
                sender=self.user,
                receiver_content_type=ct,
                receiver_object_id__in=[self.get_id(o) for o in self.indexed[ct]]
            )

            for obj in self.indexed[ct]:
                for like in likes:
                    if like.receiver_object_id == self.get_id(obj):
                        obj.liked = True
                yield obj


class LikedObjectsNode(template.Node):

    def __init__(self, objects, user, varname):
        self.objects = template.Variable(objects)
        self.user = template.Variable(user)
        self.varname = varname

    def render(self, context):
        user = self.user.resolve(context)
        objects = self.objects.resolve(context)
        context[self.varname] = ObjectDecorator(user, objects).objects()
        return ""


@register.tag
def liked(parser, token):
    """
    {% liked objects by user as varname %}
    """
    tag, objects, _, user, _, varname = token.split_contents()
    return LikedObjectsNode(objects, user, varname)
