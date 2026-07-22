/* CE Class Visits — DataTables + bulk action JS
 * Depends on: jQuery, DataTables, blockUI, sweetalert (swal)
 * Global vars injected by index.html template:
 *   CV_API_URL, CV_NN_API_URL, CV_NN_ADD_URL, CV_BULK_ACTION_URL, CV_CSRFTOKEN
 */

var tbl_visits;
var tbl_not_needed;

/* ---- Close helpers called from iframes ---- */
window.closeVisitModal = function () {
    $('#visit_modal').modal('hide');
};
window.closeNNModal = function () {
    $('#nn_modal').modal('hide');
};

$(document).ready(function () {

    /* ===== All Visits columns (built before init so the payment column can be
       conditionally inserted to stay in sync with the <thead>) ===== */
    var visitColumns = [
        /* Checkbox column */
        {
            orderable: false,
            searchable: false,
            render: function (data, type, row) {
                return '<input type="checkbox" class="chk-visit" value="' + row.id + '">';
            },
        },
        /* visit_date */
        { data: 'visit_date', name: 'visit_date' },
        /* type_of_visit */
        { data: 'type_of_visit', name: 'type_of_visit' },
        /* class_sections */
        {
            data: 'class_sections',
            name: 'class_sections',
            orderable: false,
            render: function (data) {
                if (!data || !data.length) return '—';
                return data.map(function (s) {
                    return s.course.name + ' @ ' + (s.highschool ? s.highschool.name : '') +
                        '<br><span class="text-muted">(' + s.class_number + '-' + s.section_number + ')</span>';
                }).join('<br>');
            },
        },
        /* teacher_display */
        { data: 'teacher_display', name: 'teacher_display' },
        /* visitors */
        {
            data: 'visitors',
            name: 'visitors',
            orderable: false,
            render: function (data) {
                if (!data || !data.length) return '—';
                return data.map(function (v) {
                    return v.first_name + ' ' + v.last_name;
                }).join('<br>');
            },
        },
        /* report_status */
        {
            data: 'report_status',
            name: 'report_status',
            render: function (data) {
                if (data === 'Submitted') {
                    return '<span class="badge badge-success">Submitted</span>';
                } else if (data === 'Draft') {
                    return '<span class="badge badge-warning">Draft</span>';
                }
                return '<span class="badge badge-secondary">No Report</span>';
            },
        },
    ];
    if (typeof CV_PAYMENT_TRACKING !== 'undefined' && CV_PAYMENT_TRACKING) {
        visitColumns.push({ data: 'payment_status', name: 'payment_status', orderable: false });
    }
    visitColumns.push({
        /* Actions */
        data: 'id',
        name: 'id',
        orderable: false,
        searchable: false,
        render: function (data, type, row) {
            var btns = '<div class="btn-group btn-group-sm">';

            if (row.ce_report_url) {
                btns += '<a href="#" class="btn btn-info ajax-open-visit" data-src="'
                    + row.ce_report_url + '?ajax=1">View Report</a>';
            }

            btns += '<button type="button" class="btn btn-primary dropdown-toggle" data-toggle="dropdown">Actions</button>';
            btns += '<div class="dropdown-menu">';
            btns += '<a class="dropdown-item ajax-open-visit" href="#" data-src="' + row.ce_edit_url + '">Edit Visit</a>';
            btns += '<a class="dropdown-item ajax-delete-visit" href="#" data-id="' + row.id + '" data-url="' + row.ce_delete_url + '">Delete Visit</a>';
            btns += '</div></div>';
            return btns;
        },
    });

    /* ===== All Visits DataTable ===== */
    tbl_visits = $('#tbl_visits').DataTable({
        dom: 'B<"float-left mt-3 mb-3"l><"float-right mt-3"f><"row clear">rt<"row"<"col-6"i><"col-6 float-right"p>>',
        buttons: [
            {
                extend: 'csv',
                className: 'btn btn-sm btn-primary text-white',
                text: '<i class="fas fa-file-csv"></i>&nbsp;CSV',
            },
            {
                extend: 'print',
                className: 'btn btn-sm btn-primary text-white',
                text: '<i class="fas fa-print"></i>&nbsp;Print',
            },
        ],
        orderCellsTop: true,
        fixedHeader: true,
        serverSide: true,
        processing: true,
        order: [[1, 'desc']],
        lengthMenu: [30, 50, 100],
        ajax: {
            url: CV_API_URL,
            data: function (d) {
                d.format = 'datatables';
                d.term_id = $('#frm_visits_filter select[name=term]').val();
                d.course_id = $('#frm_visits_filter select[name=course]').val();
                d.report_status = $('#frm_visits_filter select[name=report_status]').val();
            },
        },
        columns: visitColumns,
        language: { loadingRecords: '&nbsp;' },
    });

    /* Filter form reloads table */
    $(document).on('change', '#frm_visits_filter :input', function () {
        tbl_visits.ajax.reload();
    });

    /* Select-all checkbox */
    $(document).on('change', '#chk_all', function () {
        var checked = $(this).is(':checked');
        $('.chk-visit').prop('checked', checked);
    });

    /* Open manage_visit modal */
    $(document).on('click', '.ajax-open-visit', function (e) {
        e.preventDefault();
        var src = $(this).attr('data-src');
        $('#visit_modal_src').attr('src', src);
        $('#visit_modal').modal({ show: true, backdrop: 'static' });
    });

    /* Delete visit */
    $(document).on('click', '.ajax-delete-visit', function (e) {
        e.preventDefault();
        if (!confirm('Delete this visit? This cannot be undone.')) return;
        var url = $(this).data('url');
        $.blockUI();
        $.get(url, function (resp) {
            $.unblockUI();
            if (resp.success) {
                swal('Deleted', resp.message, 'success').then(function () {
                    tbl_visits.ajax.reload(null, false);
                });
            } else {
                swal('Cannot Delete', resp.message, 'warning');
            }
        }, 'json').fail(function () {
            $.unblockUI();
            swal('Error', 'Could not delete visit.', 'error');
        });
    });

    /* Reload visits table after modal closes */
    $(document).on('hidden.bs.modal', '#visit_modal', function () {
        tbl_visits.ajax.reload(null, false);
    });

    /* ===== Bulk PDF export ===== */
    $('#frm_bulk_action').on('submit', function (e) {
        e.preventDefault();
        var selected = [];
        $('.chk-visit:checked').each(function () {
            selected.push($(this).val());
        });
        if (!selected.length) {
            swal('', 'Select at least one visit.', 'warning');
            return;
        }

        var formData = $(this).serialize();
        // Append ids[] for each selected item
        $.each(selected, function (i, id) {
            formData += '&ids[]=' + encodeURIComponent(id);
        });

        $.blockUI();
        $.ajax({
            type: 'POST',
            url: CV_BULK_ACTION_URL,
            data: formData,
            xhrFields: { responseType: 'blob' },
            success: function (blob, status, xhr) {
                $.unblockUI();
                var contentType = xhr.getResponseHeader('Content-Type');
                if (contentType && contentType.indexOf('application/pdf') !== -1) {
                    var url = window.URL.createObjectURL(blob);
                    var a = document.createElement('a');
                    a.href = url;
                    a.download = 'visit_letters.pdf';
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    window.URL.revokeObjectURL(url);
                } else {
                    swal('Error', 'Unexpected response from server.', 'error');
                }
            },
            error: function (xhr) {
                $.unblockUI();
                var msg = 'Export failed.';
                try {
                    var resp = JSON.parse(xhr.responseText);
                    msg = resp.message || msg;
                } catch (ex) {}
                swal('Error', msg, 'error');
            },
        });
    });

    /* ===== Mark selected as paid ===== */
    $(document).on('click', '#btn_mark_paid', function () {
        var selected = [];
        $('.chk-visit:checked').each(function () { selected.push($(this).val()); });
        if (!selected.length) { swal('', 'Select at least one visit.', 'warning'); return; }
        if (!confirm('Mark the selected submitted report(s) as paid?')) return;
        var data = { action: 'mark_as_paid', csrfmiddlewaretoken: CV_CSRFTOKEN };
        $.blockUI();
        $.ajax({
            type: 'POST', url: CV_BULK_ACTION_URL,
            data: $.param(data) + '&' + selected.map(function (id) {
                return 'ids[]=' + encodeURIComponent(id);
            }).join('&'),
            success: function (resp) {
                $.unblockUI();
                swal('', (resp && resp.message) || 'Done', 'success').then(function () {
                    tbl_visits.ajax.reload(null, false);
                });
            },
            error: function (xhr) {
                $.unblockUI();
                var msg = 'Could not mark as paid.';
                try { msg = JSON.parse(xhr.responseText).message || msg; } catch (e) {}
                swal('Error', msg, 'error');
            }
        });
    });

    /* ===== Not-Needed DataTable ===== */
    tbl_not_needed = $('#tbl_not_needed').DataTable({
        dom: 'B<"float-left mt-3 mb-3"l><"float-right mt-3"f><"row clear">rt<"row"<"col-6"i><"col-6 float-right"p>>',
        buttons: [
            {
                extend: 'csv',
                className: 'btn btn-sm btn-primary text-white',
                text: '<i class="fas fa-file-csv"></i>&nbsp;CSV',
            },
        ],
        serverSide: true,
        processing: true,
        order: [[2, 'desc']],
        lengthMenu: [30, 50, 100],
        ajax: {
            url: CV_NN_API_URL,
            data: function (d) {
                d.format = 'datatables';
                d.term_id = $('#frm_nn_filter select[name=term]').val();
                d.course_id = $('#frm_nn_filter select[name=course]').val();
            },
        },
        columns: [
            /* class_section */
            {
                data: 'class_section',
                name: 'class_section',
                orderable: false,
                render: function (data) {
                    if (!data) return '—';
                    return data.course.name + '<br><span class="text-muted">' +
                        data.class_number + '-' + data.section_number + '</span>';
                },
            },
            { data: 'added_by_display', name: 'added_by_display' },
            { data: 'created_at', name: 'created_at' },
            /* Remove action */
            {
                data: 'remove_url',
                name: 'remove_url',
                orderable: false,
                searchable: false,
                render: function (data, type, row) {
                    return '<a href="#" class="btn btn-sm btn-danger ajax-nn-remove" data-url="' + row.remove_url + '">Remove</a>';
                },
            },
        ],
        language: { loadingRecords: '&nbsp;' },
    });

    $(document).on('change', '#frm_nn_filter :input', function () {
        tbl_not_needed.ajax.reload();
    });

    /* Remove from not-needed */
    $(document).on('click', '.ajax-nn-remove', function (e) {
        e.preventDefault();
        if (!confirm('Remove this section from the not-needed list?')) return;
        var url = $(this).data('url');
        $.blockUI();
        $.get(url, function (resp) {
            $.unblockUI();
            if (resp.success) {
                tbl_not_needed.ajax.reload(null, false);
            } else {
                swal('Error', resp.message, 'warning');
            }
        }, 'json').fail(function () {
            $.unblockUI();
            swal('Error', 'Could not remove section.', 'error');
        });
    });

    /* Open not-needed picker modal */
    $(document).on('click', '.ajax-open-modal[data-modal="#nn_modal"]', function (e) {
        e.preventDefault();
        var src = $(this).data('src');
        $('#nn_modal_src').attr('src', src);
        $('#nn_modal').modal({ show: true, backdrop: 'static' });
    });

    $(document).on('hidden.bs.modal', '#nn_modal', function () {
        tbl_not_needed.ajax.reload(null, false);
    });

    /* Auto-refresh every 5 minutes unless a row is selected */
    setInterval(function () {
        if (!tbl_visits.rows('.selected').any()) {
            tbl_visits.ajax.reload(null, false);
        }
        if (!tbl_not_needed.rows('.selected').any()) {
            tbl_not_needed.ajax.reload(null, false);
        }
    }, 5 * 60 * 1000);

});
