/* instructor_visits.js — class visit DataTable for instructor portal */
$(document).ready(function () {

  var tbl = $('#tbl_instructor_visits').DataTable({
    orderCellsTop: true,
    fixedHeader: true,
    serverSide: true,
    processing: true,
    ajax: {
      url: CV_API_URL,
      data: function (d) { d.format = 'datatables'; }
    },
    order: [[1, 'desc']],
    lengthMenu: [30, 50, 100],
    language: { loadingRecords: '&nbsp;' },
    columns: [
      // 0 — checkbox
      {
        data: 'id',
        orderable: false,
        searchable: false,
        render: function (data) {
          return '<input type="checkbox" class="chk_row" value="' + data + '">';
        }
      },
      // 1 — visit_date
      { data: 'visit_date' },
      // 2 — type_of_visit
      { data: 'type_of_visit', defaultContent: '-' },
      // 3 — sections
      {
        data: 'class_sections',
        orderable: false,
        render: function (data) {
          if (!data || !data.length) return '-';
          return data.map(function (s) {
            return s.course.name + ' (' + s.class_number + '-' + s.section_number + ')';
          }).join('<br>');
        }
      },
      // 4 — visitors
      {
        data: 'visitors',
        orderable: false,
        render: function (data) {
          if (!data || !data.length) return '-';
          return data.map(function (v) {
            return v.first_name + ' ' + v.last_name;
          }).join('<br>');
        }
      },
      // 5 — confirmed
      {
        data: 'confirmed',
        render: function (data) {
          return data
            ? '<span class="badge badge-success">Yes</span>'
            : '<span class="badge badge-secondary">No</span>';
        }
      },
      // 6 — report status
      {
        data: 'has_submitted_report',
        render: function (data) {
          return data
            ? '<span class="badge badge-primary">Submitted</span>'
            : '<span class="badge badge-light text-muted">Not yet</span>';
        }
      },
      // 7 — actions
      {
        data: null,
        orderable: false,
        searchable: false,
        render: function (data, type, row) {
          var html = '';
          if (row.has_submitted_report) {
            html += '<a href="' + row.report_detail_url + '" class="btn btn-xs btn-outline-primary">View Report</a>';
          }
          return html || '-';
        }
      }
    ]
  });

  // Select-all checkbox
  $('#chk_all').on('change', function () {
    var checked = this.checked;
    $('.chk_row').prop('checked', checked);
    updateExportButton();
  });

  tbl.on('change', '.chk_row', updateExportButton);

  function updateExportButton() {
    var count = $('.chk_row:checked').length;
    $('#btn_export_pdf').prop('disabled', count === 0);
  }

  // Export PDF bulk action
  $('#btn_export_pdf').on('click', function () {
    var ids = $('.chk_row:checked').map(function () {
      return this.value;
    }).get();

    if (!ids.length) return;

    var $form = $('#frm_bulk');
    $('#hidden_ids').empty();
    ids.forEach(function (id) {
      $('<input>').attr({ type: 'hidden', name: 'ids[]', value: id })
        .appendTo('#hidden_ids');
    });
    $form.submit();
  });
});
