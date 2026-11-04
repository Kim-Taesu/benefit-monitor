"""Conservative text scopes for change detection; no facts or numbers are inferred."""
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit
from ..validation import official


VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
SKIP = {'script', 'style', 'nav', 'footer'}


class BodyText(HTMLParser):
    def __init__(self, seoul_scope=False):
        super().__init__()
        self.frames = []
        self.parts = []
        self.regions = {'seoul_news': [], 'main': [], 'article': []}
        self.seoul_scope = seoul_scope

    def handle_starttag(self, tag, attrs):
        if len(self.frames) >= 256:
            raise ValueError('Body markup nesting exceeds limit')
        skip = tag in SKIP or bool(self.frames and self.frames[-1][1])
        region = None
        key = tag if tag in ('main', 'article') else None
        if self.seoul_scope and tag == 'div' and 'news_detail_cont' in (dict(attrs).get('class') or '').split():
            key = 'seoul_news'
        if key and not skip:
            region = {'parts': [], 'closed': False}
            self.regions[key].append(region)
        if tag not in VOID:
            self.frames.append((tag, skip, region))

    def handle_data(self, data):
        if self.frames and self.frames[-1][1]:
            return
        self.parts.append(data)
        for _, _, region in self.frames:
            if region is not None:
                region['parts'].append(data)

    def handle_endtag(self, tag):
        for index in range(len(self.frames) - 1, -1, -1):
            if self.frames[index][0] == tag:
                region = self.frames[index][2]
                if region is not None:
                    region['closed'] = True
                del self.frames[index:]
                break

    def result(self):
        # Multiple/unclosed scopes are ambiguous: compare the full document instead.
        for tag in ('seoul_news', 'main', 'article'):
            regions = self.regions[tag]
            if regions:
                if len(regions) == 1 and regions[0]['closed']:
                    return ' '.join(' '.join(regions[0]['parts']).split()), tag
                break
        return ' '.join(' '.join(self.parts).split()), 'document'


def extract_body(page, target=''):
    seoul_scope = bool(target and official(target, ['mediahub.seoul.go.kr'])
                       and re.fullmatch(r'/archives/[0-9]+', urlsplit(target).path))
    parser = BodyText(seoul_scope)
    parser.feed(page)
    parser.close()
    return parser.result()
