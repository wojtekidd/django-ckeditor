from __future__ import absolute_import

import os
from datetime import datetime

from django.conf import settings
from django.core.files.storage import default_storage
from django.http import HttpResponse
from django.shortcuts import render_to_response
from django.template import RequestContext
from django.views import generic
from django.views.decorators.csrf import csrf_exempt

from ckeditor_uploader import image_processing
from ckeditor_uploader import utils
from ckeditor_uploader.forms import SearchForm


def get_upload_filename(upload_name, user):
    # If CKEDITOR_RESTRICT_BY_USER is True upload file to user specific path.
    if getattr(settings, 'CKEDITOR_RESTRICT_BY_USER', False):
        user_path = user.username
    else:
        user_path = ''

    # Generate date based path to put uploaded file.
    date_path = datetime.now().strftime('%Y/%m/%d')

    # Complete upload path (upload_path + date_path).
    upload_path = os.path.join(
        settings.CKEDITOR_UPLOAD_PATH, user_path, date_path)

    if getattr(settings, "CKEDITOR_UPLOAD_SLUGIFY_FILENAME", True):
        upload_name = utils.slugify_filename(upload_name)

    return default_storage.get_available_name(os.path.join(upload_path, upload_name))


class ImageUploadView(generic.View):
    http_method_names = ['post']

    def post(self, request, **kwargs):
        """
        Uploads a file and send back its URL to CKEditor.
        """
        uploaded_file = request.FILES['upload']

        backend = image_processing.get_backend()
        self._verify_file(backend, uploaded_file)
        saved_path = self._save_file(request, uploaded_file)
        self._create_thumbnail_if_needed(backend, saved_path)
        url = utils.get_media_url(saved_path)

        # Respond with Javascript sending ckeditor upload url.
        return HttpResponse("""
        <script type='text/javascript'>
            window.parent.CKEDITOR.tools.callFunction({0}, '{1}');
        </script>""".format(request.GET['CKEditorFuncNum'], url))

    def _verify_file(self, backend, uploaded_file):
        try:
            backend.image_verify(uploaded_file)
        except utils.NotAnImageException:
            return self._on_verification_failure()

    def _on_verification_failure(self):
        pass

    @staticmethod
    def _save_file(request, uploaded_file):
        filename = get_upload_filename(uploaded_file.name, request.user)
        saved_path = default_storage.save(filename, uploaded_file)
        return saved_path

    @staticmethod
    def _create_thumbnail_if_needed(backend, saved_path):
        if backend.should_create_thumbnail(saved_path):
            backend.create_thumbnail(saved_path)


upload = csrf_exempt(ImageUploadView.as_view())


def get_image_files(user=None, path=''):
    """
    Recursively walks all dirs under upload dir and generates a list of
    full paths for each file found.
    """
    # If a user is provided and CKEDITOR_RESTRICT_BY_USER is True,
    # limit images to user specific path, but not for superusers.
    STORAGE_DIRECTORIES = 0
    STORAGE_FILES = 1

    restrict = getattr(settings, 'CKEDITOR_RESTRICT_BY_USER', False)
    if user and not user.is_superuser and restrict:
        user_path = user.username
    else:
        user_path = ''

    browse_path = os.path.join(settings.CKEDITOR_UPLOAD_PATH, user_path, path)

    try:
        storage_list = default_storage.listdir(browse_path)
    except NotImplementedError:
        return
    except OSError:
        return

    for filename in storage_list[STORAGE_FILES]:
        if os.path.splitext(filename)[0].endswith('_thumb') or os.path.basename(filename).startswith('.'):
            continue
        filename = os.path.join(browse_path, filename)
        yield filename

    for directory in storage_list[STORAGE_DIRECTORIES]:
        if directory.startswith('.'):
            continue
        directory_path = os.path.join(path, directory)
        for element in get_image_files(user=user, path=directory_path):
            yield element


def get_files_browse_urls(user=None):
    """
    Recursively walks all dirs under upload dir and generates a list of
    thumbnail and full image URL's for each file found.
    """
    files = []
    for filename in get_image_files(user=user):
        src = utils.get_media_url(filename)
        visible_filename = None
        if getattr(settings, 'CKEDITOR_IMAGE_BACKEND', None):
            if is_image(src):
                thumb = utils.get_media_url(utils.get_thumb_filename(filename))
            else:
                thumb = utils.get_icon_filename(filename)
                visible_filename = os.path.split(filename)[1]
                if len(visible_filename) > 20:
                    visible_filename = visible_filename[0:19] + '...'
        else:
            thumb = src
        files.append({
            'thumb': thumb,
            'src': src,
            'is_image': is_image(src),
            'visible_filename': visible_filename,
        })

    return files


def is_image(path):
    ext = path.split('.')[-1].lower()
    return ext in ['jpg', 'jpeg', 'png', 'gif']


def browse(request):
    
    files = get_files_browse_urls(request.user)
    if request.method == 'POST':
        form = SearchForm(request.POST)
        if form.is_valid():
            files = filter(lambda d: form.cleaned_data.get('q', '').lower() in d['visible_filename'].lower(), files)
    else:
        form = SearchForm()

    show_dirs = getattr(settings, 'CKEDITOR_BROWSE_SHOW_DIRS')
    dir_list = sorted(set(os.path.dirname(f['src']) for f in files), reverse=True)

    # Ensures there are no objects created from Thumbs.db files - ran across this problem while developing on Windows
    if os.name == 'nt': 
        files = [f for f in files if os.path.basename(f['src']) != 'Thumbs.db']

    context = RequestContext(request, {
        'show_dirs': show_dirs,
        'dirs': dir_list,
        'files': files,
        'form': form
    })
    return render_to_response('ckeditor/browse.html', context)

