"""Pagination tuned for a phone on a slow connection."""

from collections import OrderedDict

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """Page-number pagination with a client-settable, server-capped size.

    ``count`` is included because the app draws "12 of 40" headers; the cap
    exists because ``?page_size=100000`` is otherwise a free denial-of-service
    against the database.
    """

    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response(OrderedDict([
            ('count', self.page.paginator.count),
            ('page', self.page.number),
            ('pages', self.page.paginator.num_pages),
            ('page_size', self.get_page_size(self.request)),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('results', data),
        ]))


class LargePagination(StandardPagination):
    """For reference data the app caches once (subjects, levels, topics)."""

    page_size = 100
    max_page_size = 500
