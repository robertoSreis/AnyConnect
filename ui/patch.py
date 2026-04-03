def _on_queue_next(self, job: dict):
        """Chamado pela fila quando há job aguardando após fim de impressão."""
        if self._queue_dialog_open:
            return
        if getattr(self, "_printing_active", False):
            return

        self._queue_dialog_open = True
        self._tray_show()

        from ui.print_queue_widget import BedClearDialog
        dlg = BedClearDialog(job, self)
        dlg.exec()
        action = dlg.get_action()

        self._queue_dialog_open = False

        if action == BedClearDialog.RESULT_OK:
            # Mesa confirmada — remove da fila e abre para impressão
            self._print_queue.dequeue()
            filepath = job.get("filepath", "")
            if filepath and os.path.isfile(filepath):
                if hasattr(self, "_tabs"):
                    self._tabs.setCurrentIndex(0)
                if hasattr(self, "_print"):
                    self._print.load_file_from_arg(filepath)
            if self._tray:
                self._tray.showMessage(
                    "SE3D — NEXT PRINT",
                    f"LOADING: {job.get('task_name', 'arquivo')}",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )

        elif action == BedClearDialog.RESULT_SKIP:
            # Pular — move para o final e tenta o próximo
            self._print_queue.dequeue()
            self._print_queue.enqueue(job)
            if not self._print_queue.is_empty():
                next_job = self._print_queue.peek()
                if next_job and next_job.get("filepath") != job.get("filepath"):
                    self._on_queue_next(next_job)

        elif action == BedClearDialog.RESULT_CANCEL:
            # Remover da fila permanentemente
            self._print_queue.dequeue()
            # Verifica se há mais jobs na fila
            if not self._print_queue.is_empty():
                QTimer.singleShot(500, self._print_queue.on_print_finished)

        else:
            # RESULT_WAIT (ou fechar com X) — não faz nada, job permanece na fila
            # O próximo evento de print_finished vai disparar novamente
            pass