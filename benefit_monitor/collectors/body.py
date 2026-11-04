"""Conservative text scopes for change detection; no facts or numbers are inferred."""
from html.parser import HTMLParser


VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
SKIP = {'script', 'style', 'nav', 'footer'}


class BodyText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.frames = []
        self.parts = []
        self.regions = {'main': [], 'article': []}

    def handle_starttag(self, tag, attrs):
        if len(self.frames) >= 256:
            raise ValueError('Body markup nesting exceeds limit')
        skip = tag in SKIP or bool(self.frames and self.frames[-1][1])
        region = None
        if tag in self.regions and not skip:
            region = {'parts': [], 'closed': False}
            self.regions[tag].append(region)
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
        for tag in ('main', 'article'):
            regions = self.regions[tag]
            if regions:
                if len(regions) == 1 and regions[0]['closed']:
                    return ' '.join(' '.join(regions[0]['parts']).split()), tag
                break
        return ' '.join(' '.join(self.parts).split()), 'document'


def extract_body(page):
    parser = BodyText()
    parser.feed(page)
    parser.close()
    return parser.result()
