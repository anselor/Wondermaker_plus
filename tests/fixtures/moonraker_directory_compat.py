# SPDX-License-Identifier: GPL-3.0-or-later
# Relevant methods from the printer Moonraker FileManager.
# Copyright (C) 2020 Eric Callahan <arksine.code@gmail.com>
from __future__ import annotations
import os, pathlib, shutil, asyncio
class FileManager:
    def check_reserved_path(
        self,
        req_path: StrOrPath,
        need_write: bool,
        raise_error: bool = True
    ) -> bool:
        if isinstance(req_path, str):
            req_path = pathlib.Path(req_path)
        req_path = req_path.expanduser().resolve()
        if ".git" in req_path.parts:
            if raise_error:
                raise self.server.error(
                    "Access to .git folders is forbidden", 403
                )
            return True
        for name, (res_path, can_read) in self.reserved_paths.items():
            if (
                (res_path == req_path or res_path in req_path.parents) and
                (need_write or not can_read)
            ):
                if not raise_error:
                    return True
                raise self.server.error(
                    f"Access to file {req_path.name} forbidden by reserved "
                    f"path '{name}'", 403
                )
        return False

    async def _handle_directory_request(self,
                                        web_request: WebRequest
                                        ) -> Dict[str, Any]:
        directory = web_request.get_str('path', "gcodes")
        root, dir_path = self._convert_request_path(directory)
        req_type = web_request.get_request_type()
        if req_type == RequestType.GET:
            is_extended = web_request.get_boolean('extended', False)
            # Get list of files and subdirectories for this target
            dir_info = self._list_directory(dir_path, root, is_extended)
            return dir_info
        async with self.sync_lock:
            self.check_reserved_path(dir_path, True)
            action = "create_dir"
            if req_type == RequestType.POST and root in self.full_access_roots:
                # Create a new directory
                self.sync_lock.setup("create_dir", dir_path)
                try:
                    os.mkdir(dir_path)
                except Exception as e:
                    raise self.server.error(str(e))
                self.fs_observer.on_item_create(root, dir_path, is_dir=True)
            elif req_type == RequestType.DELETE and root in self.full_access_roots:
                # Remove a directory
                action = "delete_dir"
                if directory.strip("/") == root:
                    raise self.server.error(
                        "Cannot delete root directory")
                if not os.path.isdir(dir_path):
                    raise self.server.error(
                        f"Directory does not exist ({directory})")
                self.sync_lock.setup("delete_dir", dir_path)
                force = web_request.get_boolean('force', False)
                if force:
                    # Make sure that the directory does not contain a file
                    # loaded by the virtual_sdcard
                    self._handle_operation_check(dir_path)
                    try:
                        await self.event_loop.run_in_thread(
                            shutil.rmtree, dir_path)
                    except Exception:
                        raise
                else:
                    try:
                        os.rmdir(dir_path)
                    except Exception as e:
                        raise self.server.error(str(e))
                self.fs_observer.on_item_delete(root, dir_path, is_dir=True)
            else:
                raise self.server.error("Operation Not Supported", 405)
            return self._sched_changed_event(action, root, dir_path)

    def _list_directory(self,
                        path: str,
                        root: str,
                        is_extended: bool = False
                        ) -> Dict[str, Any]:
        if not os.path.isdir(path):
            raise self.server.error(
                f"Directory does not exist ({path})")
        self.check_reserved_path(path, False)
        flist: Dict[str, Any] = {'dirs': [], 'files': []}
        for fname in os.listdir(path):
            full_path = os.path.join(path, fname)
            if not os.path.exists(full_path):
                continue
            path_info = self.get_path_info(full_path, root)
            if os.path.isdir(full_path):
                path_info['dirname'] = fname
                flist['dirs'].append(path_info)
            elif os.path.isfile(full_path):
                path_info['filename'] = fname
                # Check to see if a filelist update is necessary
                ext = os.path.splitext(fname)[-1].lower()
                if (
                    root == "gcodes" and
                    ext in VALID_GCODE_EXTS and
                    is_extended
                ):
                    rel_path = self.get_relative_path(root, full_path)
                    metadata: Dict[str, Any] = self.gcode_metadata.get(
                        rel_path, {})
                    path_info.update(metadata)
                flist['files'].append(path_info)
        usage = shutil.disk_usage(path)
        flist['disk_usage'] = usage._asdict()
        flist['root_info'] = {
            'name': root,
            'permissions': "rw" if root in self.full_access_roots else "r"
        }
        return flist

    def get_path_info(
        self, path: StrOrPath, root: str, raise_error: bool = True
    ) -> Dict[str, Any]:
        if isinstance(path, str):
            path = pathlib.Path(path)
        real_path = path.resolve()
        try:
            fstat = path.stat()
        except Exception:
            if raise_error:
                raise
            return {"modified": 0, "size": 0, "permissions": ""}
        if ".git" in real_path.parts:
            permissions = ""
        else:
            permissions = "rw"
            if (
                root not in self.full_access_roots or
                (path.is_symlink() and path.is_file())
            ):
                permissions = "r"
            for name, (res_path, can_read) in self.reserved_paths.items():
                if (res_path == real_path or res_path in real_path.parents):
                    if not can_read:
                        permissions = ""
                        break
                    permissions = "r"
        return {
            'modified': fstat.st_mtime,
            'size': fstat.st_size,
            'permissions': permissions
        }

    def list_dir(self,
                 directory: str,
                 simple_format: bool = False
                 ) -> Union[Dict[str, Any], List[str]]:
        # List a directory relative to its root.
        if directory[0] == "/":
            directory = directory[1:]
        parts = directory.split("/", 1)
        root = parts[0]
        if root not in self.file_paths:
            raise self.server.error(
                f"Invalid Directory Request: {directory}")
        path = self.file_paths[root]
        if len(parts) == 1:
            dir_path = path
        else:
            dir_path = os.path.join(path, parts[1])
        if not os.path.isdir(dir_path):
            raise self.server.error(
                f"Directory does not exist ({dir_path})")
        flist = self._list_directory(dir_path, root)
        if simple_format:
            simple_list = []
            for dirobj in flist['dirs']:
                simple_list.append("*" + dirobj['dirname'])
            for fileobj in flist['files']:
                fname = fileobj['filename']
                ext = os.path.splitext(fname)[-1].lower()
                if root == "gcodes" and ext in VALID_GCODE_EXTS:
                    simple_list.append(fname)
            return simple_list
        return flist

